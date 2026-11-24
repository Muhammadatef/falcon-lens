"""Hunt mode runtime (docs/design/HUNTER.md section 3): sources, egress-bound HTTP, store, scheduler, submission.

Off unless FL_HUNT_ENABLED=true. The Sentinel never contacts a candidate domain: it talks only to the DoH
resolver and crt.sh, through `hunt-egress`. Every contact with a candidate happens in the worker cascade.
"""
