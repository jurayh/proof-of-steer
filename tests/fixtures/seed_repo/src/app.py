"""Fixture pre-existing module. The synthetic session edits this file
without ever Writing it, so transcript-only replay has no base for it."""

def greet(name):
    return "hello " + name

def farewell(name):
    return "bye " + name

VERSION = "1.0"
