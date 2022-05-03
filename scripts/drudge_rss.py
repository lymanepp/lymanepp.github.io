#!/usr/bin/python
"""Scrape drudgereport.com into RSS feed."""

import json
import re
import sys
import time
import xml.etree.ElementTree as etree
from datetime import datetime
from http import HTTPStatus
from typing import Any, Mapping, Sequence, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, element

DRUDGE_BASE_URL = "http://www.drudgereport.com"
RSS_FILE_NAME = "drudge.rss"
JSON_FILE_NAME = "drudge.json"
SKIP_LIST = ["www.wsj.com"]


def main() -> int:
    """Generate RSS feed for drudgereport.com"""
    print("Started at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)

    if not (live_links := _read_live_links()):
        return 1

    now = time.time()
    prior = _read_prior()
    current = _build_current(live_links, prior, now)
    _write_prior(current)

    rss_tree = _build_rss_tree(current, now)
    _write_rss_file(rss_tree)

    print("Ended at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)
    return 0


def _read_prior() -> Mapping[str, Mapping[str, Any]]:
    try:
        with open(JSON_FILE_NAME, "r", encoding="utf8") as json_file:
            last = json.load(json_file)
    except FileNotFoundError:
        last = {}
    return last


def _write_prior(current: Mapping[str, Any]) -> None:
    with open(JSON_FILE_NAME, "w", encoding="utf8") as json_file:
        json.dump(current, json_file, indent=4)


def _read_live_links() -> Sequence[Tuple[str, str]] | None:
    response = requests.get(DRUDGE_BASE_URL, timeout=10)
    if response.status_code != HTTPStatus.OK:
        print(
            f"Received HTTP status {response.status_code} reading from {DRUDGE_BASE_URL}"
        )
        return None

    pattern = '<A [^>]*HREF="([^"]+)"[^>]*>([^<]+)</A>'
    return re.findall(pattern, response.content.decode("latin-1"))


def _build_current(
    current_links: Sequence[Tuple[str, str]],
    prior: Mapping[str, Mapping[str, Any]],
    time_added: float,
) -> Mapping[str, Mapping[str, Any]]:

    current: dict[str, Mapping[str, Any]] = {}

    for link, title in current_links:
        if _is_skipped(link):
            continue

        link = link.replace("\n", "").replace("\r", "")
        title = title.strip()

        if "://" not in link:
            link = DRUDGE_BASE_URL + link

        current[link] = prior.get(link) or {
            "title": title,
            "added": time_added,
            "description": _get_description(link),
        }

        if link not in prior:
            print("New link:", link, flush=True)

    # Add missing items that are less than 24 hours old
    for link, meta in prior.items():
        if link not in current and (time_added - meta["added"]) < 86400:
            current[link] = meta

    return current


def _is_skipped(link: str) -> bool:
    """Is URL skipped."""
    url = urlparse(link)
    return url.netloc in SKIP_LIST


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
            description = soup.find("meta", property="og:description") or soup.find(
                "meta", property="description"
            )
            if isinstance(description, element.Tag):
                return (
                    description.attrs["content"]
                    .strip()
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .replace("  ", " ")
                )
    except Exception as exc:
        print("Except in get_description: %s", exc)
        print("Link = %s", link)
    return ""


def _build_rss_tree(
    current: Mapping[str, Mapping[str, Any]], now: float
) -> etree.ElementTree:
    rss = etree.Element("rss")
    rss.set("version", "2.0")

    channel = etree.SubElement(rss, "channel")

    chan_title = etree.SubElement(channel, "title")
    chan_title.text = "DRUDGE REPORT"

    chan_link = etree.SubElement(channel, "link")
    chan_link.text = DRUDGE_BASE_URL

    etree.SubElement(channel, "description")

    sorted_dict = sorted(
        current.items(), key=lambda item: (item[1]["added"], item[0]), reverse=True
    )

    for link, meta in sorted_dict:
        added = meta["added"]
        if (now - added) > 86400:
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
        item_desc.text = f"<b>{base_url}</b><br>{description}"

    return etree.ElementTree(rss)


def _write_rss_file(rss: etree.ElementTree) -> None:
    etree.indent(rss)
    rss.write(RSS_FILE_NAME, xml_declaration=True, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
