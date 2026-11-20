#!/usr/bin/env python3
"""Construye la propuesta breve de fase 1 desde Markdown + Mermaid exportado."""
from pathlib import Path
import markdown
from weasyprint import HTML, CSS

ROOT = Path(__file__).resolve().parent
source = ROOT / 'entrega1-clara.md'
css = ROOT / 'entrega1-clara.css'
output = ROOT / 'Entrega-1-revisada.pdf'
body = markdown.markdown(source.read_text(encoding='utf-8'), extensions=['tables', 'fenced_code', 'sane_lists'])
html = '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Propuesta de diseño y arquitectura · Fase 1</title></head><body>' + body + '</body></html>'
HTML(string=html, base_url=str(ROOT)).write_pdf(str(output), stylesheets=[CSS(filename=str(css))])
print(output)
