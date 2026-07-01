from __future__ import annotations

import argparse
import json

from rescueops.risk_engine import scan_account
from rescueops.slack_blocks import render_blocks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a RescueOps demo scan.")
    parser.add_argument("account_id", help="Demo account id, for example: acme")
    parser.add_argument(
        "--blocks",
        action="store_true",
        help="Print Slack Block Kit JSON instead of a text summary.",
    )
    args = parser.parse_args()

    case = scan_account(args.account_id)

    if args.blocks:
        print(json.dumps(render_blocks(case), indent=2))
        return

    print(f"Revenue Rescue: {case.account.name}")
    print(f"Risk: {case.risk_score}% {case.risk_level}")
    print(f"Revenue at risk: USD {case.metrics['revenue_at_risk']:,}")
    print(f"Expected revenue protected: USD {case.metrics['expected_revenue_protected']:,}")
    print(f"Evidence source: {case.metrics['evidence_source']}")
    print(
        "Mean Time To Rescue: "
        f"{case.metrics['old_time_to_plan']} -> {case.metrics['new_time_to_plan']} "
        f"({case.metrics['mean_time_to_rescue_reduction_pct']}% reduction)"
    )
    print("")
    print("Root causes:")
    for cause in case.root_causes:
        print(f"- {cause}")
    print("")
    print("Recommended actions:")
    for action in case.actions:
        print(f"- {action.title} | owner: {action.owner} | due: {action.due}")


if __name__ == "__main__":
    main()
