"""A workflow is the single reception point for one UI request.

It calls services and does not own a table: the service that owns a table
is the only module that writes it. See docs/specs/layering.md.
"""
