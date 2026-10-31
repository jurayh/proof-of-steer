#!/usr/bin/env python3
import sys
BOOKS = []
def add(title):
    BOOKS.append(title)
    print("Added " + title + " to your list")
def show():
    for number, title in enumerate(BOOKS, 1):
        print(str(number) + ". " + title)
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "add":
        add(sys.argv[2])
    elif cmd == "list":
        show()
if __name__ == "__main__":
    main()
