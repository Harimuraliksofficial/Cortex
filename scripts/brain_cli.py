import os
import sys
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.server import remember, recall, handoff, forget

def main():
    parser = argparse.ArgumentParser(description="Knowledge Brain MCP CLI Bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # remember
    p_remember = subparsers.add_parser("remember")
    p_remember.add_argument("--title", required=True)
    p_remember.add_argument("--content", required=True)
    p_remember.add_argument("--topic", default="general")
    p_remember.add_argument("--kind", default="decision")
    p_remember.add_argument("--subject-key", default="")
    p_remember.add_argument("--authority", default="user")
    p_remember.add_argument("--origin-trust", default="direct_user")
    p_remember.add_argument("--replaces-previous", action="store_true")

    # recall
    p_recall = subparsers.add_parser("recall")
    p_recall.add_argument("--query", default="")
    p_recall.add_argument("--token-budget", type=int, default=1200)

    # handoff
    p_handoff = subparsers.add_parser("handoff")
    p_handoff.add_argument("--summary", required=True)
    p_handoff.add_argument("--next-steps", required=True)
    p_handoff.add_argument("--blockers", default="")

    # forget
    p_forget = subparsers.add_parser("forget")
    p_forget.add_argument("--target", required=True)

    args = parser.parse_args()

    if args.command == "remember":
        res = remember(
            title=args.title,
            content=args.content,
            topic=args.topic,
            kind=args.kind,
            subject_key=args.subject_key,
            authority=args.authority,
            origin_trust=args.origin_trust,
            replaces_previous=args.replaces_previous
        )
        print(res)

    elif args.command == "recall":
        res = recall(query=args.query, token_budget=args.token_budget)
        print(res)

    elif args.command == "handoff":
        res = handoff(summary=args.summary, next_steps=args.next_steps, blockers=args.blockers)
        print(res)

    elif args.command == "forget":
        res = forget(target=args.target)
        print(res)

if __name__ == "__main__":
    main()
