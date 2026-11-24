# Installed release identity in About

The native WonderMaker+ row displays the installed release tag when the
installer runs from an exactly tagged, clean checkout. Otherwise it displays
branch@short-commit, with +modified for tracked local changes. Detached HEAD
uses detached@short-commit. An archive without Git metadata falls back to the
immutable UI build identity rather than inventing a release version.

The installer writes WMP_RELEASE_IDENTITY into its existing transactional
screen-service override. Normal rollback and uninstall restore the previous
override; no separate state file or polling loop is added. The native screen
reads this environment value when constructing About. The details page shows
the full release identity and the independent UI build ID. Long list captions
retain the beginning and ending while shortening the middle.

Validation: 371 release-identity, preload and delivery checks passed. The two
native lifecycle/factory-font checks also passed. Real Git tests cover tagged,
modified and detached checkouts; archive tests avoid borrowing identity from
an unrelated parent repository. The environment publication test asserts the
identity key and restoration of the prior service override.

No motion behavior changes in this follow-up. No release push or tag is implied.
