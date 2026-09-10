cat <<EOF > check.py
from collections import Counter
import re

text = "'quote' 'start end' ' middle'word a'b a'b'c".lower()
pattern = re.compile(r"[a-z0-9']+")
raw_words = pattern.findall(text)
words = [w.strip("'") for w in raw_words if w.strip("'")]
print(Counter(words))
EOF
python3 check.py
