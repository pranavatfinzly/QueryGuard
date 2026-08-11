"""Outbound integrations: GitHub, Claude, and p6spy log parsing.

Pipeline stages call into these; nothing here imports a pipeline stage back.
Keeping the dependency one-way is what lets a stage be tested without a network.
"""
