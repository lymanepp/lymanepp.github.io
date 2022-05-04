"""Scrape drudgereport.com into RSS feed."""
import json
import sys
import xml.etree.ElementTree as etree
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, Type
from urllib.parse import urlparse
from yarl import URL

import requests
from bs4 import BeautifulSoup, element

DRUDGE_BASE_URL = "http://www.drudgereport.com"
RSS_FILE_NAME = "docs/drudge.rss"
JSON_FILE_NAME = "work/drudge.json"
PAY_WALL_LIST = ["www.wsj.com"]
RETENTION_PERIOD = timedelta(days=1)

JsonType = dict[str, Any] | list[Any] | str | float | Type[None]

LiveLinksType = list[tuple[str, str]]
DataModelType = dict[str, dict[str, Any]]


def main() -> int:
    """Generate RSS feed for drudgereport.com"""
    print("Started at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)

    if not (live_links := _read_live_links()):
        return 1

    now = datetime.now(tz=timezone.utc)
    prior = _read_json(JSON_FILE_NAME, default={})
    assert isinstance(prior, dict)

    for link, meta in prior.items():
        if not meta["description"]:
            desc = _get_msn_description(link)
            meta["description"] = desc

    current = _build_current(live_links, prior, now)
    _write_json(JSON_FILE_NAME, current)

    rss_tree = _build_rss_tree(current, now)
    _write_rss_file(rss_tree)

    print("Ended at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)
    return 0


def _read_json(file_name: str, default=None) -> JsonType:
    try:
        with open(file_name, "r", encoding="utf8") as file:
            obj = json.load(file)
    except FileNotFoundError:
        obj = default
    return obj


def _write_json(file_name: str, obj: JsonType) -> None:
    with open(file_name, "w", encoding="utf8") as file:
        json.dump(obj, file, indent=4)


def _read_live_links() -> LiveLinksType | None:
    response = requests.get(DRUDGE_BASE_URL, timeout=10)
    if response.status_code != HTTPStatus.OK:
        print(
            f"Received HTTP status {response.status_code} reading from {DRUDGE_BASE_URL}"
        )
        return None

    html = response.content.decode("latin-1")
    soup = BeautifulSoup(html, 'html.parser')

    return [(tag.attrs["href"], tag.text) for tag in soup.find_all("a")]


def _build_current(
    current_links: LiveLinksType, prior: DataModelType, now: datetime
) -> DataModelType:

    current: DataModelType = {}

    for link, title in current_links:
        if _is_pay_wall(link):
            continue

        link = link.replace("\n", "").replace("\r", "").replace(" ", "")
        title = title.strip()

        if "://" not in link:
            link = DRUDGE_BASE_URL + link

        current[link] = prior.get(link) or {
            "title": title,
            "added": now.isoformat(),
            "description": _get_description(link),
        }

        if link not in prior:
            print("New link:", link, flush=True)

    # Add missing items that are less than 24 hours old
    for link, meta in prior.items():
        added = datetime.fromisoformat(meta["added"])
        if link not in current and (now - added) < RETENTION_PERIOD:
            current[link] = meta

    return dict(
        sorted(
            current.items(), key=lambda item: (item[1]["added"], item[0]), reverse=True
        )
    )


def _is_pay_wall(link: str) -> bool:
    """Is URL skipped."""
    url = urlparse(link)
    return url.netloc in PAY_WALL_LIST


def _get_description(link: str) -> str:
    """Get meta description for URL."""
    if link.startswith("http://www.mcclatchydc.com"):
        return "CRAP"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0"
        }
        response = requests.get(link, headers=headers, timeout=5)
        if response.status_code == HTTPStatus.OK:
            soup = BeautifulSoup(response.content, "html5lib")
            description = soup.find("meta", property="og:description") or soup.find("meta", property="description")
            if isinstance(description, element.Tag):
                return (
                    description.attrs["content"]
                    .strip()
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .replace("  ", " ")
                )
            return _get_msn_description(link)
    except Exception as exc:
        print("Except in get_description: %s", exc)
        print("Link = %s", link)
    return ""


def _get_msn_description(link: str) -> str:
    # https://assets.msn.com/content/view/v2/Detail/en-us/AAWPSy9
    url = URL(link)
    if url.host != "www.msn.com" or not url.name.startswith("ar-"):
        return ""
    meta_url = URL("https://assets.msn.com/content/view/v2/Detail/en-us") / url.name[3:]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0"
    }
    json_resp = requests.get(meta_url, headers=headers, timeout=5)
    if json_resp.status_code != HTTPStatus.OK:
        return ""
    meta = json.loads(json_resp.content)
    return meta.get("title")


def _build_rss_tree(current: DataModelType, now: datetime) -> etree.ElementTree:
    rss = etree.Element("rss")
    rss.set("version", "2.0")

    channel = etree.SubElement(rss, "channel")

    chan_title = etree.SubElement(channel, "title")
    chan_title.text = "DRUDGE REPORT"

    chan_link = etree.SubElement(channel, "link")
    chan_link.text = DRUDGE_BASE_URL

    etree.SubElement(channel, "description")

    for link, meta in current.items():
        added = datetime.fromisoformat(meta["added"])
        if (now - added) > RETENTION_PERIOD:
            continue

        base_url = urlparse(link).netloc
        if base_url.startswith("www."):
            base_url = base_url[4:]

        description = meta["description"].strip()

        item = etree.SubElement(channel, "item")

        item_title = etree.SubElement(item, "title")
        item_title.text = meta["title"]

        item_link = etree.SubElement(item, "link")
        item_link.text = link

        item_desc = etree.SubElement(item, "description")
        item_desc.text = f"{base_url} ► {description}" if description else base_url

    return etree.ElementTree(rss)


def _write_rss_file(rss: etree.ElementTree) -> None:
    etree.indent(rss)
    rss.write(RSS_FILE_NAME, xml_declaration=True, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
