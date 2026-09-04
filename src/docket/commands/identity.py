"""docket identity: the Device/Attended commit trailers for this machine.

docket does not commit; its two launchd agents do, and this is how they stamp
who made the commit. Trailers rather than `user.name` on purpose — authorship
on GitHub stays the user's, while `git log --grep="Attended: false"` still
finds every commit no human stood behind.
"""

from __future__ import annotations

from docket.config import Config, DocketError


def run_identity(cfg: Config, *, unattended: bool = False) -> str:
    if not cfg.identity.present:
        raise DocketError(
            f'no [identity] table in {cfg.path} — add device = "<role>" '
            "(mac, cnslab, hermes: a role, never a hostname)"
        )
    return cfg.identity.trailers(unattended)
