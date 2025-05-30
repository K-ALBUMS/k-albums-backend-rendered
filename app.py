from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re

app = Flask(__name__)
CORS(app)

@app.route('/api/upload-invoice', methods=['POST'])
def upload_invoice():
    if 'invoice_pdf' not in request.files:
        return jsonify({"error": "Aucun fichier PDF trouvé"}), 400
    file = request.files['invoice_pdf']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier sélectionné"}), 400

    try:
        file_content_in_memory = io.BytesIO(file.read())
        reader = PdfReader(file_content_in_memory)
        full_text = "".join([page.extract_text() + "\n" for page in reader.pages if page.extract_text()])

        # Pour debug si besoin
        # print("--- TEXTE PDF ---\n", full_text[:1500], "\n--- FIN PDF ---")

        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        parsed_products = []

        # Expression pour détecter un produit (avec Release, quantité, prix, total)
        product_re = re.compile(
            r'^(?P<name>.+?)Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$'
        )
        # Accessoire avec variation "Size:" séparé
        size_line_re = re.compile(r'^(Size|Ver|Version|Type)\s*:\s*(?P<variation>.+)$', re.IGNORECASE)

        i = 0
        while i < len(lines):
            line = lines[i]
            # Cas général : produit tout sur la même ligne (albums, lightsticks, etc.)
            match = product_re.match(line)
            if match:
                name = match.group("name").strip()
                date = match.group("date") or "N/A"
                quantity = int(match.group("quantity"))
                unit_price = float(match.group("unit_price"))
                # Gérer variation si nom fini par ) et ligne suivante commence par Size:
                if (i + 1 < len(lines)) and size_line_re.match(lines[i + 1]):
                    variation = size_line_re.match(lines[i + 1]).group("variation").strip()
                    name = f"{name}({variation})"
                    i += 1  # On saute la ligne variation
                parsed_products.append({
                    "name": name,
                    "quantity": quantity,
                    "unit_price_usd": unit_price,
                    "release_date": date
                })
                i += 1
                continue

            # Cas accessoire ou produit avec variation sur plusieurs lignes
            # ex: nom + Release: (vide) + Size + quantité/prix
            if (i + 2 < len(lines)) and 'Release' in lines[i + 1] and size_line_re.match(lines[i + 2]):
                name = line
                date = re.search(r'Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})?', lines[i + 1])
                date_val = date.group("date") if date else "N/A"
                variation = size_line_re.match(lines[i + 2]).group("variation").strip()
                # La ligne après Size contient les quantités/prix
                if (i + 3 < len(lines)) and re.match(r'^\d+\s*\$\d+\.\d+\s*\$\d+\.\d+$', lines[i + 3]):
                    qty_line = lines[i + 3]
                    q_match = re.match(r'^(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$', qty_line)
                    if q_match:
                        parsed_products.append({
                            "name": f"{name} ({variation})",
                            "quantity": int(q_match.group("quantity")),
                            "unit_price_usd": float(q_match.group("unit_price")),
                            "release_date": date_val
                        })
                        i += 4
                        continue

            # Si ce n'est pas un produit, passer à la ligne suivante
            i += 1

        # Frais d'envoi
        shipping_cost = None
        bank_fee = None
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if shipping_match:
            shipping_cost = shipping_match.group(1)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if bank_fee_match:
            bank_fee = bank_fee_match.group(1)

        return jsonify({
            "message": "Extraction produits (robuste, séparé ligne par ligne)",
            "filename": file.filename,
            "shipping_cost_usd": shipping_cost,
            "bank_transfer_fee_usd": bank_fee,
            "parsed_products": parsed_products,
            "DEVELOPMENT_full_text_for_debug": full_text
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur interne majeure lors du traitement du PDF: {str(e)}"}), 500

    return jsonify({"error": "Un problème est survenu avec le fichier ou fichier non traité."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
