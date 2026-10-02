from pathlib import Path
import pymupdf

output = Path(__file__).resolve().parent / 'data' / 'inbox' / 'demo_nombre_dos_lineas.pdf'
output.parent.mkdir(parents=True, exist_ok=True)

document = pymupdf.open()
page = document.new_page(width=612, height=792)
page.insert_text((72, 90), 'ESCRITURA DE PRUEBA', fontsize=16)
page.insert_text((72, 170), 'ACREDITADO:', fontsize=11)
page.insert_text((155, 170), 'MARIA DEL CARMEN RODRIGUEZ', fontsize=13)
page.insert_text((155, 194), 'DE LA GARZA', fontsize=13)
page.insert_text((72, 260), 'Este archivo sirve para probar la seleccion multilinea.', fontsize=10)
document.save(output)
print(output)
