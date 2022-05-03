#!/usr/bin/python
import json
import re
import sys
import time
import xml.etree.ElementTree as etree
from datetime import datetime
from urllib.parse import urlparse

import html5lib
import requests
from bs4 import BeautifulSoup

RSS_FILE_NAME = "drudge.rss"
JSON_FILE_NAME = "drudge.json"
SKIP_LIST = ["www.wsj.com"]


def indent(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def get_description(link):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:81.0) Gecko/20100101 Firefox/81.0"
        }
        response = requests.get(link, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html5lib")
            description = soup.find("meta", property="og:description") or soup.find(
                "meta", property="description"
            )
            if description:
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


def is_skipped(link):
    url = urlparse(link)
    return url.netloc in SKIP_LIST


def main():
    print("Started at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)

    response = requests.get("http://www.drudgereport.com/", timeout=10)
    if response.status_code != 200:
        return 1

    pattern = '<A [^>]*HREF="([^"]+)"[^>]*>([^<]+)</A>'
    results = re.findall(pattern, response.content.decode("latin-1"))
    if not results:
        return 2

    try:
        with open(JSON_FILE_NAME) as json_file:
            last = json.load(json_file)
    except FileNotFoundError:
        last = {}

    current = {}
    now = time.time()

    for result in results:
        link = result[0].replace("\n", "").replace("\r", "")
        title = result[1].strip()

        if "://" not in link:
            link = "http://www.drudgereport.com" + link

        if is_skipped(link):
            continue

        if link in last:
            meta = last[link]
        elif link.startswith("http://www.mcclatchydc.com"):
            meta = {"title": title, "added": now, "description": "CRAP"}
            pass
        else:
            meta = {"title": title, "added": now, "description": get_description(link)}

        current[link] = meta

        if link not in last:
            print("New link:", link, flush=True)

    # Add missing items that are less than 24 hours old
    for link, meta in list(last.items()):
        if link not in current and (now - meta["added"]) < 86400:
            current[link] = meta

    with open(JSON_FILE_NAME, "w") as json_file:
        json.dump(current, json_file, indent=4)

    # Create index sorted by date
    index = []
    for link, meta in list(current.items()):
        added = meta["added"]
        if (now - added) < 86400:
            index.append((added, link, meta))

    index = sorted(index, reverse=True)

    # Build RSS file
    rss = etree.Element("rss")
    rss.set("version", "2.0")

    channel = etree.SubElement(rss, "channel")

    chan_title = etree.SubElement(channel, "title")
    chan_link = etree.SubElement(channel, "link")
    chan_desc = etree.SubElement(channel, "description")

    chan_title.text = "DRUDGE REPORT"
    chan_link.text = "http://www.drudgereport.com"
    chan_desc.text = ""

    for added, link, meta in index:
        item = etree.SubElement(channel, "item")
        item_title = etree.SubElement(item, "title")
        item_link = etree.SubElement(item, "link")
        item_desc = etree.SubElement(item, "description")

        item_link.text = link
        item_title.text = meta["title"]
        item_desc.text = (
            "<b>" + urlparse(link).netloc + "</b><br>" + meta["description"]
        ).strip()

    indent(rss)
    tree = etree.ElementTree(rss)
    tree.write(RSS_FILE_NAME, xml_declaration=True, encoding="utf-8", method="xml")

    print("Ended at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)
    print(json.dumps(current, indent=4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
