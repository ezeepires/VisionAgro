import sys
from pathlib import Path

# Adiciona o diretório VisionAgro ao path do Python
base_dir = Path(__file__).resolve().parent.parent / "VisionAgro"
sys.path.insert(0, str(base_dir))

from main import app
