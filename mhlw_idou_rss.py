import requests
import hashlib
import re
import time
import xml.etree.ElementTree as ET

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime, parsedate_to_datetime


# --------------------------------------------------
# 設定
# --------------------------------------------------

SOURCE_URL = (
    "https://www.mhlw.go.jp/"
    "stf/shingi/shingi-idou_127786.html"
)

OUTPUT = Path(__file__).parent / "mhlw_idou.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
}


# --------------------------------------------------
# 既存RSSを読み込む
# --------------------------------------------------

old_items = {}

if OUTPUT.exists():

    try:
        old_tree = ET.parse(OUTPUT)

        for item in old_tree.getroot().findall(
            "./channel/item"
        ):

            guid = item.findtext(
                "guid",
                ""
            )

            if guid:

                old_items[guid] = {
                    "title": item.findtext(
                        "title",
                        ""
                    ),
                    "link": item.findtext(
                        "link",
                        ""
                    ),
                    "description": item.findtext(
                        "description",
                        ""
                    ),
                    "pubDate": item.findtext(
                        "pubDate",
                        ""
                    ),
                    "guid": guid,
                }

    except Exception as e:

        print(
            "既存RSS読み込みエラー:",
            e
        )

        print(
            "安全のため今回は更新しません。"
        )

        raise SystemExit(0)


print(
    "既存RSS件数:",
    len(old_items)
)


# --------------------------------------------------
# 厚生労働省ページ取得
# --------------------------------------------------

response = None

MAX_RETRIES = 3

for attempt in range(
    1,
    MAX_RETRIES + 1
):

    try:

        print(
            f"厚生労働省ページ取得 "
            f"{attempt}/{MAX_RETRIES}"
        )

        response = requests.get(
            SOURCE_URL,
            headers=HEADERS,
            timeout=30
        )

        print(
            "HTTP:",
            response.status_code
        )

        response.raise_for_status()

        break

    except requests.RequestException as e:

        print(
            "取得失敗:",
            e
        )

        response = None

        if attempt < MAX_RETRIES:

            print(
                "10秒待って再試行します。"
            )

            time.sleep(10)


# --------------------------------------------------
# 取得できなかった場合
# --------------------------------------------------

if response is None:

    print()
    print(
        "厚生労働省ページを取得できませんでした。"
    )

    print(
        "今回はRSSを更新しません。"
    )

    print(
        "既存の mhlw_idou.xml を"
        "そのまま維持します。"
    )

    print(
        "次回の定期実行で再度確認します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# HTML解析
# --------------------------------------------------

try:

    soup = BeautifulSoup(
        response.content,
        "html.parser"
    )

except Exception as e:

    print(
        "HTML解析エラー:",
        e
    )

    print(
        "今回はRSSを更新しません。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 「議事要旨」を取得
# --------------------------------------------------

current_items = []

seen_links = set()


for a in soup.find_all(
    "a",
    href=True
):

    anchor_text = a.get_text(
        " ",
        strip=True
    )

    if "議事要旨" not in anchor_text:
        continue

    element = a
    date_match = None

    # リンク周辺から開催日を探す
    for _ in range(8):

        if element is None:
            break

        text = element.get_text(
            " ",
            strip=True
        )

        date_match = re.search(
            r"(20\d{2})年\s*"
            r"(\d{1,2})月\s*"
            r"(\d{1,2})日",
            text
        )

        if date_match:
            break

        element = element.parent


    if not date_match:
        continue


    year = int(
        date_match.group(1)
    )

    month = int(
        date_match.group(2)
    )

    day = int(
        date_match.group(3)
    )


    link = urljoin(
        SOURCE_URL,
        a["href"]
    )


    if link in seen_links:
        continue

    seen_links.add(link)


    # 開催日の正午をpubDateにする
    dt = datetime(
        year,
        month,
        day,
        12,
        0,
        0,
        tzinfo=JST
    )


    title = (
        f"医道審議会（医道分科会） "
        f"{year}年{month}月{day}日 "
        f"議事要旨"
    )


    guid = hashlib.sha256(
        link.encode("utf-8")
    ).hexdigest()


    current_items.append(
        {
            "title": title,
            "link": link,
            "description": (
                "厚生労働省 "
                "医道審議会（医道分科会）の議事要旨"
            ),
            "pubDate": format_datetime(dt),
            "guid": guid,
        }
    )


print(
    "今回取得:",
    len(current_items),
    "件"
)


# --------------------------------------------------
# 0件なら更新しない
# --------------------------------------------------

if len(current_items) == 0:

    print(
        "議事要旨を1件も取得できませんでした。"
    )

    print(
        "ページ構造変更などの可能性があるため、"
        "今回はRSSを更新しません。"
    )

    print(
        "既存の mhlw_idou.xml を"
        "そのまま維持します。"
    )

    raise SystemExit(0)


# --------------------------------------------------
# 既存RSSと統合
# --------------------------------------------------

all_items = []

seen_guids = set()


for item in current_items:

    if item["guid"] not in seen_guids:

        all_items.append(item)

        seen_guids.add(
            item["guid"]
        )


for guid, item in old_items.items():

    if guid not in seen_guids:

        all_items.append(item)

        seen_guids.add(guid)


# --------------------------------------------------
# 新しい順
# --------------------------------------------------

def get_date(item):

    try:

        return parsedate_to_datetime(
            item["pubDate"]
        )

    except Exception:

        return datetime.min.replace(
            tzinfo=timezone.utc
        )


all_items.sort(
    key=get_date,
    reverse=True
)


# --------------------------------------------------
# RSS作成
# --------------------------------------------------

rss = ET.Element(
    "rss",
    version="2.0"
)

channel = ET.SubElement(
    rss,
    "channel"
)


ET.SubElement(
    channel,
    "title"
).text = (
    "厚生労働省 医道審議会（医道分科会）"
)


ET.SubElement(
    channel,
    "link"
).text = SOURCE_URL


ET.SubElement(
    channel,
    "description"
).text = (
    "厚生労働省 医道審議会"
    "（医道分科会）の議事要旨更新情報"
)


ET.SubElement(
    channel,
    "language"
).text = "ja"


# --------------------------------------------------
# RSS記事
# --------------------------------------------------

for item in all_items:

    element = ET.SubElement(
        channel,
        "item"
    )


    ET.SubElement(
        element,
        "title"
    ).text = item["title"]


    ET.SubElement(
        element,
        "link"
    ).text = item["link"]


    ET.SubElement(
        element,
        "description"
    ).text = item["description"]


    ET.SubElement(
        element,
        "pubDate"
    ).text = item["pubDate"]


    guid_element = ET.SubElement(
        element,
        "guid"
    )

    guid_element.set(
        "isPermaLink",
        "false"
    )

    guid_element.text = item["guid"]


# --------------------------------------------------
# XML保存
# --------------------------------------------------

tree = ET.ElementTree(
    rss
)

ET.indent(
    tree,
    space="  "
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True
)


# --------------------------------------------------
# 結果
# --------------------------------------------------

print()
print("RSS作成成功")

print(
    "RSS保存件数:",
    len(all_items),
    "件"
)

print(
    "保存先:",
    OUTPUT
)

print()
print("取得記事:")


for i, item in enumerate(
    current_items,
    start=1
):

    print()
    print(
        f"[{i}] "
        f"{item['title']}"
    )

    print(
        "    ",
        item["link"]
    )