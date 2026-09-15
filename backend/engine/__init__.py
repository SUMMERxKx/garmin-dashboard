"""The calculation engine: baselines, deviations, and what they mean.

Pure. Nothing in here reads a file, opens a database, calls the network, or asks what
time it is. Every function takes values and returns values, which is what makes the
whole engine testable without a single mock.
"""
