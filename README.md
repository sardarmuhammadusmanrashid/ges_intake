# GES Engineering Onsite Exercise

Start with **TASK.md**. Everything works offline with Python 3.10+.

```bash
python tools/make_inbox.py inbox
python -m ges_intake --library library --clients clients run --client C-1001 --inbox inbox\day1 --inbox inbox\day2 --as-of 2026-03-03 --outbox outbox.jsonl

```
