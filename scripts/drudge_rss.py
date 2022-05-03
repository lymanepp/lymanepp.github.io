#!/usr/bin/python
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as etree
from datetime import datetime
from urllib.parse import urlparse

import html5lib
import requests
from bs4 import BeautifulSoup

rssFileName = "drudge.rss"
jsonFileName = "drudge.json"

blacklist = ["www.wsj.com"]


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
    except:
        # print(link)
        # print(sys.exc_info())
        pass
    return ""


def is_blacklisted(link):
    url = urlparse(link)
    for item in blacklist:
        if item == url.netloc:
            return True
    return False


print("Started at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)

response = requests.get("http://www.drudgereport.com/", timeout=10)
if response.status_code != 200:
    sys.exit(1)

pattern = '<A [^>]*HREF="([^"]+)"[^>]*>([^<]+)</A>'
results = re.findall(pattern, response.content.decode("latin-1"))
if not results:
    sys.exit(2)

try:
    with open(jsonFileName) as jsonFile:
        last = json.load(jsonFile)
except:
    last = {}

current = {}
now = time.time()

for result in results:
    link = result[0].replace("\n", "").replace("\r", "")
    title = result[1].strip()

    if "://" not in link:
        link = "http://www.drudgereport.com" + link

    if is_blacklisted(link):
        continue

    if link in last:
        dict = last[link]
    elif link.startswith("http://www.mcclatchydc.com"):
        dict = {"title": title, "added": now, "description": "CRAP"}
        pass
    else:
        # print('Getting description:', link, flush=True)
        dict = {"title": title, "added": now, "description": get_description(link)}

    current[link] = dict

    if link not in last:
        print("New link:", link, flush=True)

# Add missing items that are less than 24 hours old
for link, dict in list(last.items()):
    if link not in current and (now - dict["added"]) < 86400:
        current[link] = dict

try:
    with open(jsonFileName, "w") as jsonFile:
        json.dump(current, jsonFile, indent=4)
except:
    pass

# Create index sorted by date
index = []
for link, dict in list(current.items()):
    added = dict["added"]
    if (now - added) < 86400:
        index.append((added, link, dict))

index.sort()
index.reverse()

# Build RSS file
rss = etree.Element("rss")
rss.set("version", "2.0")

channel = etree.SubElement(rss, "channel")

chanTitle = etree.SubElement(channel, "title")
chanLink = etree.SubElement(channel, "link")
chanDesc = etree.SubElement(channel, "description")

chanTitle.text = "DRUDGE REPORT"
chanLink.text = "http://www.drudgereport.com"
chanDesc.text = ""

for added, link, dict in index:
    item = etree.SubElement(channel, "item")
    itemTitle = etree.SubElement(item, "title")
    itemLink = etree.SubElement(item, "link")
    itemDesc = etree.SubElement(item, "description")

    itemLink.text = link
    itemTitle.text = dict["title"]
    itemDesc.text = (
        "<b>" + urlparse(link).netloc + "</b><br>" + dict["description"]
    ).strip()

indent(rss)
tree = etree.ElementTree(rss)
tree.write(rssFileName, xml_declaration=True, encoding="utf-8", method="xml")

print("Ended at:", datetime.now().strftime("%d/%m/%Y %H:%M:%S"), flush=True)
sys.exit(0)
