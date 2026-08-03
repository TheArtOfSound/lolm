# P0 release trigger

This commit exists only to run the repository's normal pull-request validation for the immutable P0 artifact-delivery release:

`892f5d2802afdea73d8f381d5922553b00b99b9e`

The default-branch one-shot workflow is required to match this trigger branch and this trigger commit exactly before it may deploy that release SHA.
