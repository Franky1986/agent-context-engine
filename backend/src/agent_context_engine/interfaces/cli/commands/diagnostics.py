from __future__ import annotations

import argparse

from ....application.diagnostics import run_doctor_checks


def cmd_doctor(args: argparse.Namespace) -> int:
    lines, exit_code = run_doctor_checks(
        check_codex_features=args.check_codex_features,
        relocation_report_requested=args.relocation_report,
    )
    for line in lines:
        print(line)
    return exit_code
