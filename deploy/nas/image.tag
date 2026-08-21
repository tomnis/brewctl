# The image brewctl runs on the NAS. This file IS the deploy.
#
# Bump the reference below and push: that commit is the promotion, and it is the
# only thing that changes what is running (see .forgejo/workflows/deploy.yml).
# Rollback is `git revert` of that commit -- which works only while the older
# image is still loaded on the NAS, since there is no registry to re-pull from.
#
# Pinned, never :latest, and never a moving branch- tag here: a moving tag makes
# "what is running" unanswerable and rollback impossible. CI loads
# catacombs/brewctl:sha-<short12> onto the NAS for every build and prints the exact
# line to paste in its run summary.
#
# Comments and blank lines are ignored; the first real line is the reference.
# apply.sh substitutes it for @IMAGE@ in app.yaml before the PUT.

catacombs/brewctl:sha-b4a927d45ba0
