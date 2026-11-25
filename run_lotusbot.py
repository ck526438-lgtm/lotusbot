"""Point d'entrée de l'exécutable Windows (PyInstaller)."""
import sys

from lotusbot.cli import main

if __name__ == "__main__":
    sys.exit(main())
