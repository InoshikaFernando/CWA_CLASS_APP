#!/usr/bin/env bash
# Backfill the release tags missing from origin.
#
# Each tag points at the FIRST commit on main carrying that APP_VERSION —
# i.e. the merge that shipped it. Derived from the repo, then cross-checked
# against the head_sha of the deploy-prod run for every release where one
# exists (11 of them); all matched.
#
# Versions that only ever reached `test` (1.18.1, most of 1.19.x, 1.20.x,
# 1.25.0-1.27.0, ...) are deliberately NOT tagged: they never shipped.
#
# Idempotent: an existing tag is left alone. Run from a clone with `origin`
# pointing at InoshikaFernando/CWA_CLASS_APP.
set -euo pipefail

git fetch origin main --tags

# 39 tags to create
created=()

if git rev-parse -q --verify "refs/tags/v1.17.5" >/dev/null; then
  echo "v1.17.5  already exists locally, skipping"
else
  git tag -a "v1.17.5" 0ffb8cbcc8892b471871b966bb4ff1fdf400eeb9 -m "Release v1.17.5 (2026-07-31)

Merge pull request #689 from InoshikaFernando/test"
  created+=("v1.17.5")
fi

if git rev-parse -q --verify "refs/tags/v1.17.6" >/dev/null; then
  echo "v1.17.6  already exists locally, skipping"
else
  git tag -a "v1.17.6" f552145c905f7fe51b77863bc590506baa201339 -m "Release v1.17.6 (2026-08-15)

Release v1.17.6: weekly release 2026-08-15 (#722)"
  created+=("v1.17.6")
fi

if git rev-parse -q --verify "refs/tags/v1.17.7" >/dev/null; then
  echo "v1.17.7  already exists locally, skipping"
else
  git tag -a "v1.17.7" e7c667a2f5bb89c276840cfa259cca99109fb647 -m "Release v1.17.7 (2026-08-17)

Release v1.17.7: homework PDF upload fix (#727)"
  created+=("v1.17.7")
fi

if git rev-parse -q --verify "refs/tags/v1.17.8" >/dev/null; then
  echo "v1.17.8  already exists locally, skipping"
else
  git tag -a "v1.17.8" 6d015aa966a9cd21eac2ee73ae40d51f5c4529a1 -m "Release v1.17.8 (2026-08-18)

Merge pull request #731 from InoshikaFernando/test"
  created+=("v1.17.8")
fi

if git rev-parse -q --verify "refs/tags/v1.17.9" >/dev/null; then
  echo "v1.17.9  already exists locally, skipping"
else
  git tag -a "v1.17.9" 1a304c59ecb3813edfbea1162f1bac3820e7bbba -m "Release v1.17.9 (2026-08-18)

Release v1.17.9: fix 403 CSRF page when switching accounts"
  created+=("v1.17.9")
fi

if git rev-parse -q --verify "refs/tags/v1.17.10" >/dev/null; then
  echo "v1.17.10  already exists locally, skipping"
else
  git tag -a "v1.17.10" 9b3fcc2a605b6b2e0d218e4258da73bac99ccffc -m "Release v1.17.10 (2026-08-19)

Merge pull request #735 from InoshikaFernando/test"
  created+=("v1.17.10")
fi

if git rev-parse -q --verify "refs/tags/v1.17.11" >/dev/null; then
  echo "v1.17.11  already exists locally, skipping"
else
  git tag -a "v1.17.11" 67846fcfdbe3564a236f549e97fd5987abe7b65a -m "Release v1.17.11 (2026-08-19)

Release 1.17.11 — restore invoice email delivery (#744)"
  created+=("v1.17.11")
fi

if git rev-parse -q --verify "refs/tags/v1.17.12" >/dev/null; then
  echo "v1.17.12  already exists locally, skipping"
else
  git tag -a "v1.17.12" d7727791881805534acee29680456bd1ea66b792 -m "Release v1.17.12 (2026-08-21)

Merge pull request #746 from InoshikaFernando/test"
  created+=("v1.17.12")
fi

if git rev-parse -q --verify "refs/tags/v1.17.13" >/dev/null; then
  echo "v1.17.13  already exists locally, skipping"
else
  git tag -a "v1.17.13" 27fae490c6350573d45db1b3b7c6a670ee8353db -m "Release v1.17.13 (2026-08-21)

Merge pull request #749 from InoshikaFernando/test"
  created+=("v1.17.13")
fi

if git rev-parse -q --verify "refs/tags/v1.17.14" >/dev/null; then
  echo "v1.17.14  already exists locally, skipping"
else
  git tag -a "v1.17.14" 7a23c39a0afe44e1153bba9a3abebd4e51c7b935 -m "Release v1.17.14 (2026-08-21)

Merge pull request #751 from InoshikaFernando/test"
  created+=("v1.17.14")
fi

if git rev-parse -q --verify "refs/tags/v1.17.15" >/dev/null; then
  echo "v1.17.15  already exists locally, skipping"
else
  git tag -a "v1.17.15" 79a1d6c93b9b8a3347bd4e7178aafd4eee595726 -m "Release v1.17.15 (2026-08-21)

Merge pull request #753 from InoshikaFernando/test"
  created+=("v1.17.15")
fi

if git rev-parse -q --verify "refs/tags/v1.17.16" >/dev/null; then
  echo "v1.17.16  already exists locally, skipping"
else
  git tag -a "v1.17.16" cc8c1ed88dcbd02199b15496086b1266f547e777 -m "Release v1.17.16 (2026-08-21)

Merge pull request #755 from InoshikaFernando/test"
  created+=("v1.17.16")
fi

if git rev-parse -q --verify "refs/tags/v1.17.17" >/dev/null; then
  echo "v1.17.17  already exists locally, skipping"
else
  git tag -a "v1.17.17" 3afec6d60d85bc7eb82353215d439d50b12d2aa2 -m "Release v1.17.17 (2026-08-21)

Merge pull request #759 from InoshikaFernando/test"
  created+=("v1.17.17")
fi

if git rev-parse -q --verify "refs/tags/v1.17.18" >/dev/null; then
  echo "v1.17.18  already exists locally, skipping"
else
  git tag -a "v1.17.18" 1a5b7765b1319faea0defbf9f6485a66dd008afd -m "Release v1.17.18 (2026-08-21)

Merge pull request #761 — Release 1.17.18 (add/remove answers in the question editor)"
  created+=("v1.17.18")
fi

if git rev-parse -q --verify "refs/tags/v1.17.19" >/dev/null; then
  echo "v1.17.19  already exists locally, skipping"
else
  git tag -a "v1.17.19" 0baffd18a1048cd51db942e7fbe2cee97a0d2453 -m "Release v1.17.19 (2026-08-21)

Merge pull request #763 from InoshikaFernando/test"
  created+=("v1.17.19")
fi

if git rev-parse -q --verify "refs/tags/v1.17.20" >/dev/null; then
  echo "v1.17.20  already exists locally, skipping"
else
  git tag -a "v1.17.20" b436e278ce50771524b88a6cad676d41350d167a -m "Release v1.17.20 (2026-08-21)

Merge pull request #765 — Release 1.17.20 (stop flagging correct questions as broken)"
  created+=("v1.17.20")
fi

if git rev-parse -q --verify "refs/tags/v1.17.21" >/dev/null; then
  echo "v1.17.21  already exists locally, skipping"
else
  git tag -a "v1.17.21" 63b9a0c799e7e858cc35a215cc8af6d983402e16 -m "Release v1.17.21 (2026-08-21)

Merge pull request #767 — Release 1.17.21 (flag MCQs breaking 1 correct + 3 wrong)"
  created+=("v1.17.21")
fi

if git rev-parse -q --verify "refs/tags/v1.17.22" >/dev/null; then
  echo "v1.17.22  already exists locally, skipping"
else
  git tag -a "v1.17.22" fdab2372ce92fba7cd087e7f13b0b0dcb39fd135 -m "Release v1.17.22 (2026-08-21)

Merge pull request #769 — Release 1.17.22 (a fix for every reported problem)"
  created+=("v1.17.22")
fi

if git rev-parse -q --verify "refs/tags/v1.17.23" >/dev/null; then
  echo "v1.17.23  already exists locally, skipping"
else
  git tag -a "v1.17.23" faa47720c0ba55cb44fec4592486482e5ea62c3b -m "Release v1.17.23 (2026-08-22)

Merge pull request #779 — Release 1.17.23"
  created+=("v1.17.23")
fi

if git rev-parse -q --verify "refs/tags/v1.17.24" >/dev/null; then
  echo "v1.17.24  already exists locally, skipping"
else
  git tag -a "v1.17.24" 346eb2accb908b55a09939c6652b633abca75f16 -m "Release v1.17.24 (2026-08-23)

Merge pull request #780 from InoshikaFernando/test"
  created+=("v1.17.24")
fi

if git rev-parse -q --verify "refs/tags/v1.17.25" >/dev/null; then
  echo "v1.17.25  already exists locally, skipping"
else
  git tag -a "v1.17.25" f3c15f5265501f868e1f6d650f9be567c2d95f1f -m "Release v1.17.25 (2026-08-23)

Merge pull request #784 — release 1.17.25"
  created+=("v1.17.25")
fi

if git rev-parse -q --verify "refs/tags/v1.17.26" >/dev/null; then
  echo "v1.17.26  already exists locally, skipping"
else
  git tag -a "v1.17.26" 7751e81ead2701ba2ce4e6c0f16ebc6daee80161 -m "Release v1.17.26 (2026-08-23)

Merge pull request #787 — Release v1.17.26"
  created+=("v1.17.26")
fi

if git rev-parse -q --verify "refs/tags/v1.17.27" >/dev/null; then
  echo "v1.17.27  already exists locally, skipping"
else
  git tag -a "v1.17.27" 50126bd2182c890835a165da6911016b5f2610c9 -m "Release v1.17.27 (2026-08-23)

Merge pull request #792 from InoshikaFernando/test"
  created+=("v1.17.27")
fi

if git rev-parse -q --verify "refs/tags/v1.17.28" >/dev/null; then
  echo "v1.17.28  already exists locally, skipping"
else
  git tag -a "v1.17.28" ef95acd091b09361d33cfa280cddacffdddd95ec -m "Release v1.17.28 (2026-08-24)

Merge pull request #795 from InoshikaFernando/test"
  created+=("v1.17.28")
fi

if git rev-parse -q --verify "refs/tags/v1.17.29" >/dev/null; then
  echo "v1.17.29  already exists locally, skipping"
else
  git tag -a "v1.17.29" 7d4c71042315937dc3a233454cf30dd8dec78474 -m "Release v1.17.29 (2026-08-24)

Release v1.17.29"
  created+=("v1.17.29")
fi

if git rev-parse -q --verify "refs/tags/v1.17.30" >/dev/null; then
  echo "v1.17.30  already exists locally, skipping"
else
  git tag -a "v1.17.30" 85d467a35be804a48408d6f0022dc6ca7425ef24 -m "Release v1.17.30 (2026-08-24)

Merge pull request #801 from InoshikaFernando/test"
  created+=("v1.17.30")
fi

if git rev-parse -q --verify "refs/tags/v1.18.0" >/dev/null; then
  echo "v1.18.0  already exists locally, skipping"
else
  git tag -a "v1.18.0" d60f9da6e2482b3c6bc484f40f0df8f10357c57a -m "Release v1.18.0 (2026-08-25)

Release v1.18.0: leaderboard, report automation, super-admin View as"
  created+=("v1.18.0")
fi

if git rev-parse -q --verify "refs/tags/v1.18.2" >/dev/null; then
  echo "v1.18.2  already exists locally, skipping"
else
  git tag -a "v1.18.2" ea4b1e319b26cf6fb05f7b725ae751760d0cbda3 -m "Release v1.18.2 (2026-08-25)

Release v1.18.2: progress report school scoping, practice beyond homework, school leaderboard"
  created+=("v1.18.2")
fi

if git rev-parse -q --verify "refs/tags/v1.18.3" >/dev/null; then
  echo "v1.18.3  already exists locally, skipping"
else
  git tag -a "v1.18.3" 0571e412181abe03f2cf5d76f3a632adbd6ac4ba -m "Release v1.18.3 (2026-08-26)

Release v1.18.3: preview a student's actual report before sending it"
  created+=("v1.18.3")
fi

if git rev-parse -q --verify "refs/tags/v1.19.9" >/dev/null; then
  echo "v1.19.9  already exists locally, skipping"
else
  git tag -a "v1.19.9" c90659700a66f26f9fd4970915137abe77467798 -m "Release v1.19.9 (2026-08-28)

Release 1.19.9 — per-subject progress reports, letterhead, and a cheaper CI"
  created+=("v1.19.9")
fi

if git rev-parse -q --verify "refs/tags/v1.19.11" >/dev/null; then
  echo "v1.19.11  already exists locally, skipping"
else
  git tag -a "v1.19.11" 18c58796071d1f3772c208d06f5bb5e3ec31c927 -m "Release v1.19.11 (2026-08-28)

Release 1.19.11 — the preview stops hiding students, and coding practice reports by topic"
  created+=("v1.19.11")
fi

if git rev-parse -q --verify "refs/tags/v1.19.15" >/dev/null; then
  echo "v1.19.15  already exists locally, skipping"
else
  git tag -a "v1.19.15" ad81cbe0f4e821789e6a47bad2e2d882a53ebc48 -m "Release v1.19.15 (2026-08-29)

Release 1.19.15 — number patterns marked on what the question actually asks"
  created+=("v1.19.15")
fi

if git rev-parse -q --verify "refs/tags/v1.21.0" >/dev/null; then
  echo "v1.21.0  already exists locally, skipping"
else
  git tag -a "v1.21.0" 527ddd3ebaba827923c415b8af8b3910d17ae2e8 -m "Release v1.21.0 (2026-08-30)

Release 1.21.0 — the v1 mobile API, written answers marked on what they are worth, and preview a question as a student"
  created+=("v1.21.0")
fi

if git rev-parse -q --verify "refs/tags/v1.21.2" >/dev/null; then
  echo "v1.21.2  already exists locally, skipping"
else
  git tag -a "v1.21.2" 52be427d8d7391f3e1410d274f12e9989f75ca1e -m "Release v1.21.2 (2026-08-30)

Release 1.21.2 — coordinates you can see, AI marking that refuses to guess, and question health that stops crying wolf"
  created+=("v1.21.2")
fi

if git rev-parse -q --verify "refs/tags/v1.21.3" >/dev/null; then
  echo "v1.21.3  already exists locally, skipping"
else
  git tag -a "v1.21.3" 0abb5118d7f47dcf0522cc8272ba389caede5424 -m "Release v1.21.3 (2026-08-30)

Release 1.21.3 — filter the students list and the report preview to subscribed students"
  created+=("v1.21.3")
fi

if git rev-parse -q --verify "refs/tags/v1.22.0" >/dev/null; then
  echo "v1.22.0  already exists locally, skipping"
else
  git tag -a "v1.22.0" 60a9449b6b184949e125338540035ab236f9328a -m "Release v1.22.0 (2026-08-30)

Release 1.22.0 — question automation schedule: weekly homework from a teaching plan"
  created+=("v1.22.0")
fi

if git rev-parse -q --verify "refs/tags/v1.23.0" >/dev/null; then
  echo "v1.23.0  already exists locally, skipping"
else
  git tag -a "v1.23.0" 6bd5f39f330983cc846a2444363db9723ffcf16f -m "Release v1.23.0 (2026-08-30)

Release 1.23.0 — question availability while planning, and the report download that was missing sections"
  created+=("v1.23.0")
fi

if git rev-parse -q --verify "refs/tags/v1.24.1" >/dev/null; then
  echo "v1.24.1  already exists locally, skipping"
else
  git tag -a "v1.24.1" 086feef3ed8e61ae58a6d3908519509eee49ae69 -m "Release v1.24.1 (2026-08-31)

Release 1.24.1 — weekly messages can be scheduled again, and the report says what to do next"
  created+=("v1.24.1")
fi

if git rev-parse -q --verify "refs/tags/v1.28.0" >/dev/null; then
  echo "v1.28.0  already exists locally, skipping"
else
  git tag -a "v1.28.0" 7f046cbead093846bc6c78a176cb6256fe1e721d -m "Release v1.28.0 (2026-09-01)

Release 1.28.0 — three more question types now come straight out of a PDF"
  created+=("v1.28.0")
fi

if [ ${#created[@]} -eq 0 ]; then
  echo "Nothing to create."; exit 0
fi

echo
echo "Created ${#created[@]} tags: ${created[*]}"
echo
read -r -p "Push them to origin? [y/N] " reply
[ "$reply" = "y" ] || { echo "Not pushed. Remove with: git tag -d ${created[*]}"; exit 0; }

git push origin "${created[@]}"
echo "Done."
