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
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        parsed_products = []

        # On parcourt deux lignes à la fois : (nom du produit, puis "Release : ..." avec quantité/prix)
        i = 0
        while i < len(lines) - 1:
            name_line = lines[i]
            details_line = lines[i + 1]

            # REGEX : repère "Release :" + date (optionnelle) + quantité + prix + total
            match = re.match(
                r'^Release\s*:\s*(?P<date>\d{4}(?:-\d{2})?(?:-\d{2})?)?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
                details_line
            )

            if match:
                name = name_line.strip()
                date = match.group("date") or "N/A"
                quantity = int(match.group("quantity"))
                unit_price = float(match.group("unit_price"))
                parsed_products.append({
                    "name": name,
                    "quantity": quantity,
                    "unit_price_usd": unit_price,
                    "release_date": date
                })
                i += 2
                continue

            # Cas accessoire sur 3 lignes : nom, "Release :", "Size: ... quantité/prix"
            match_size = (
                details_line.lower().startswith("release")
                and i + 2 < len(lines)
                and re.match(r'^(Size|Ver|Version|Type)\s*:\s*(?P<variation>.+)\d+\s*\$\d+\.\d+\s*\$\d+\.\d+$', lines[i + 2], re.IGNORECASE)
            )
            if match_size:
                name = name_line.strip()
                size_line = lines[i + 2]
                size_match = re.match(
                    r'^(Size|Ver|Version|Type)\s*:\s*(?P<variation>.+?)(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)$',
                    size_line, re.IGNORECASE
                )
                if size_match:
                    variation = size_match.group("variation").strip()
                    quantity = int(size_match.group("quantity"))
                    unit_price = float(size_match.group("unit_price"))
                    parsed_products.append({
                        "name": f"{name} ({variation})",
                        "quantity": quantity,
                        "unit_price_usd": unit_price,
                        "release_date": "N/A"
                    })
                    i += 3
                    continue

            i += 1  # Sinon passe à la ligne suivante

        # Frais d'envoi et bancaires
        shipping_cost = None
        bank_fee = None
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if shipping_match:
            shipping_cost = shipping_match.group(1)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if bank_fee_match:
            bank_fee = bank_fee_match.group(1)

        return jsonify({
            "message": "Extraction produits (OK format 2 lignes : nom puis Release/quantité/prix)",
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
