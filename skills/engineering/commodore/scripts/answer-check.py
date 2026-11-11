#!/usr/bin/env python3
"""Check an answer against the question item it answers, for the cross-file rules its schema can't express."""

import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("schema_check", Path(__file__).with_name("schema-check.py"))
schema_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema_check)


def problems(item, answer):
    if not isinstance(item, dict) or not isinstance(answer, dict):
        return ["the item and the answer must both be JSON objects"]
    errors = []
    if answer.get("id") != item.get("id"):
        errors.append(f"/id: {answer.get('id')!r} isn't the item's id {item.get('id')!r}")
    if item.get("kind") != "question":
        return [*errors, f"the item is kind {item.get('kind')!r}; only a question item's answer is written here"]
    questions = item.get("question", {}).get("questions", []) if isinstance(item.get("question"), dict) else []
    asked = {q.get("id"): q for q in questions if isinstance(q, dict)}
    answers = answer.get("answers")
    if not isinstance(answers, dict):
        return [*errors, "/answers: not an object"]
    errors += [f"/answers: question '{qid}' has no answer" for qid in asked if qid not in answers]
    for qid, given in answers.items():
        where = f"/answers/{qid}"
        if qid not in asked:
            errors.append(f"{where}: the item asks no question '{qid}'")
            continue
        if not isinstance(given, dict) or ("choice" not in given and "other" not in given):
            errors.append(f"{where}: needs a choice or an other")
            continue
        if "choice" not in given:
            continue
        labels = {o.get("label") for o in asked[qid].get("options", []) if isinstance(o, dict)}
        choice = given["choice"]
        if isinstance(choice, list) and asked[qid].get("multi") is not True:
            errors.append(f"{where}/choice: a list, but the question isn't multi")
        for label in choice if isinstance(choice, list) else [choice]:
            if label not in labels:
                errors.append(f"{where}/choice: {label!r} isn't one of the question's option labels")
    return errors


def main(argv):
    if len(argv) != 3:  # noqa: PLR2004
        print("usage: answer-check.py <item.json> <answer.json>", file=sys.stderr)
        return 2
    try:
        item, answer = (schema_check.load(path) for path in argv[1:])
    except (OSError, ValueError) as e:
        print(f"can't check: {e}", file=sys.stderr)
        return 2
    errors = problems(item, answer)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
