"""Scrape drudgereport.com into RSS feed."""
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
import json
import sys
from typing import Any, Final
from urllib.parse import urlparse
import xml.etree.ElementTree as etree

from bs4 import BeautifulSoup, element
import requests
from yarl import URL

DRUDGE_BASE_URL: Final = "http://www.drudgereport.com"
MSN_BASE_URL = "https://assets.msn.com/content/view/v2/Detail/en-us"
RSS_FILE_NAME: Final = "docs/drudge.rss"
JSON_FILE_NAME: Final = "work/drudge.json"
PAY_WALL_LIST: Final = ["www.wsj.com"]
RETENTION_PERIOD: Final = timedelta(days=1)

JsonType = dict[str, Any]
LiveLinksType = list[tuple[str, str]]
DataModelType = dict[str, dict[str, Any]]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0"
}


def main() -> int:
    """Generate RSS feed for drudgereport.com"""
    print("Started at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)

    if not (live_links := _read_live_links()):
        return 1

    now = datetime.now(tz=timezone.utc)
    prior = _read_json(JSON_FILE_NAME, default={})
    assert isinstance(prior, dict)
    current = _build_current(live_links, prior, now)
    _write_json(JSON_FILE_NAME, current)

    rss_tree = _build_rss_tree(current, now)
    _write_rss_file(rss_tree)

    print("Ended at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)
    return 0


def _read_json(file_name: str, default: JsonType) -> JsonType:
    try:
        with open(file_name, "r", encoding="utf8") as file:
            data = json.load(file)
            assert isinstance(data, dict)
            return data
    except OSError:
        return default


def _write_json(file_name: str, obj: JsonType) -> None:
    with open(file_name, "w", encoding="utf8") as file:
        json.dump(obj, file, indent=4)


def _read_live_links() -> LiveLinksType | None:
    response = requests.get(DRUDGE_BASE_URL, headers=HTTP_HEADERS, timeout=10)
    if response.status_code != HTTPStatus.OK:
        print(f"Received HTTP status {response.status_code} reading from {DRUDGE_BASE_URL}")
        return None

    html = response.content.decode("latin-1")
    soup = BeautifulSoup(html, "html.parser")

    return [(tag.attrs["href"], tag.text) for tag in soup.find_all("a")]


def _build_current(
    current_links: LiveLinksType, prior: DataModelType, now: datetime
) -> DataModelType:

    current: DataModelType = {}

    for link, title in current_links:
        if _is_pay_wall(link):
            continue

        url = URL(link)
        if not url.scheme:
            link = DRUDGE_BASE_URL + link
        elif url.scheme not in ("http", "https"):
            continue

        current[link] = prior.get(link) or {
            "title": title.split("\n")[0].strip(),
            "added": now.isoformat(),
            "description": _get_description(link),
        }

        if link not in prior:
            print("New link:", link, flush=True)

    # Add missing items that are less than 24 hours old
    keep_if_newer = now - RETENTION_PERIOD
    for link, meta in prior.items():
        added = datetime.fromisoformat(meta["added"])
        if link not in current and added > keep_if_newer:
            current[link] = meta

    return dict(sorted(current.items(), key=lambda item: (item[1]["added"], item[0]), reverse=True))


def _is_pay_wall(link: str) -> bool:
    """Is URL skipped."""
    url = urlparse(link)
    return url.netloc in PAY_WALL_LIST


def _get_description(link: str) -> str:
    """Get meta description for URL."""
    try:
        response = requests.get(link, headers=HTTP_HEADERS, timeout=5)
        if response.status_code == HTTPStatus.OK:
            soup = BeautifulSoup(response.content, "html5lib")
            description = (
                soup.find("meta", property="og:title")
                or soup.find("meta", property="title")
                or soup.find("meta", property="og:description")
                or soup.find("meta", property="description")
                or soup.find("meta", {"name": "description"})
            )
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
        print(f"Except in get_description: {exc}")
        print(f"Link = {link}")
    return ""


def _get_msn_description(link: str) -> str:
    # https://assets.msn.com/content/view/v2/Detail/en-us/AAWPSy9
    url = URL(link)
    if url.host != "www.msn.com" or not url.name.startswith("ar-"):
        return ""
    meta_url = URL(MSN_BASE_URL) / url.name[3:]
    json_resp = requests.get(str(meta_url), headers=HTTP_HEADERS, timeout=5)
    if json_resp.status_code != HTTPStatus.OK:
        return ""
    meta: JsonType = json.loads(json_resp.content)
    assert isinstance(meta, dict)
    return meta.get("title", "")


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
        item_desc.text = f"{base_url} ⮞ {description}" if description else base_url

    return etree.ElementTree(rss)


def _write_rss_file(rss: etree.ElementTree) -> None:
    etree.indent(rss)
    rss.write(RSS_FILE_NAME, xml_declaration=True, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
