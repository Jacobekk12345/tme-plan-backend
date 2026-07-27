from bs4 import BeautifulSoup
import json

date = "2026-06-25"
INPUT = "subs25-06.html"
OUTPUT = "25.06.json"

data = {}

with open(INPUT, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f, "html.parser")

subsList = soup.find("div", attrs={"data-date": date})

sections = subsList.find_all("div", class_="section")

for section in sections:
    className = section.select(".header > span")[0].text.strip()

    rows = section.find_all("div", class_="row")

    for row in rows:
        info = row.select(".info > span")[0]

        for old in info.find_all("s"):
            old.extract()

        subText = info.get_text(" ", strip=True).replace(", (*)", "")

        isCancelled = "Anulowano" in subText

        newData = {
            "isCancelled": isCancelled,
            "teacher": None,
            "classroom": None,
            "subject": None,
            "group": None
        }

        lessonNr = row.select(".period > span")[0].text
        lessonNr = lessonNr.replace("(", "").replace(")", "").replace(".", "")

        if className not in data:
            data[className] = {}

        if lessonNr not in data[className]:
            data[className][lessonNr] = {}

        if isCancelled:
            data[className][lessonNr] = newData
            continue

        if "Zastępstwa" in subText:
            subFirst, subSecond = subText.split(" - Zastępstwa", 1)

            if "Zmień salę lekcyjną" in subSecond:
                subSecond, subThird = subSecond.split(", Zmień salę lekcyjną", 1)

                if "➔" in subThird:
                    newData["classroom"] = (
                        subThird.split("➔")[-1]
                        .replace(", (*)", "")
                        .strip()
                    )

            if ":" in subFirst.split(",")[1]:
                newData["group"] = subFirst.split(",")[1].split(":")[0].strip()

            if "➔" in subFirst:
                newData["subject"] = subFirst.split("➔")[-1].strip()

            if "➔" in subSecond:
                newData["teacher"] = subSecond.split("➔")[-1].strip()

        data[className][lessonNr] = newData


with open(f"data/subs/{OUTPUT}", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4, ensure_ascii=False)