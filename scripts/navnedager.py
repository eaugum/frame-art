"""Makes frame_art/frameart/navnedager.json from Norwegian Wikipedia's "Liste over norske navnedager" (Almanakkforlaget's
calendar, revised December 2025). Run it again after a new revision:

curl -s "https://no.wikipedia.org/w/index.php?title=Liste_over_norske_navnedager&action=raw" > /tmp/navnedager.txt
python3 scripts/navnedager.py /tmp/navnedager.txt frame_art/frameart/navnedager.json
"""
import re, json, sys
MONTHS = ["januar","februar","mars","april","mai","juni","juli","august","september","oktober","november","desember"]
raw = open(sys.argv[1], encoding="utf-8").read()
out = {}
for line in raw.splitlines():
    m = re.match(r"\|\s*\[\[(\d+)\. (\w+)\]\]\s*\|\|(.*?)(\|\||$)", line)
    if not m:
        continue
    day, month, cell = int(m.group(1)), MONTHS.index(m.group(2)) + 1, m.group(3)
    links = re.findall(r"\[\[([^\]]+)\]\]", cell)
    cell = re.sub(r"\[\[[^\]]+\]\]", "@", cell).split("|")[0]  # a row with one | before its comment
    names = [l.split("|")[-1].strip() for l in links[:cell.count("@")]]
    if names:
        out["%02d-%02d" % (month, day)] = names
json.dump(dict(sorted(out.items())), open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(len(out), "days")
