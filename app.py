# app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber
import re

app = Flask(__name__)
CORS(app)

# Exemple de route de test
@app.route("/ping")
def ping():
    return jsonify({"message": "pong"})

# Ici, par exemple, votre logique pour parser une facture
def get_full_text_lines(file_path):
    with pdfplumber.open(file_path) as pdf:
        lines = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split("\n"):
                    cleaned = line.strip()
                    if cleaned:
                        lines.append(cleaned)
    return lines

def parse_products_from_lines(lines_list):
    products = []
    i = 0
    n = len(lines_list)

    # Trouver le début de la section "Product Quantity Price Total"
    while i < n and "Product Quantity Price Total" not in lines_list[i]:
        i += 1
    if i >= n:
        return []

    i += 1  # passer l'en‐tête

    date_pattern = re.compile(r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)")
    qty_price_pattern = re.compile(r"(\d+)\s*\$?([\d.,]+)")

    def is_subtotal_line(line):
        return line.strip().startswith("Subtotal")

    while i < n and not is_subtotal_line(lines_list[i]):
        name_lines = []
        # Accumuler le nom jusqu'à "Release"
        while i < n and not lines_list[i].startswith("Release"):
            text = lines_list[i].strip()
            if text and not text.startswith("Product Quantity Price Total"):
                name_lines.append(text)
            i += 1

        if i >= n:
            break

        full_name = " ".join(name_lines).strip()
        release_line = lines_list[i].strip()
        i += 1

        release_date = "N/A"
        quantity = 0
        unit_price = 0.0

        after_release = release_line[len("Release :"):].strip()
        date_match = date_pattern.match(after_release)
        if date_match:
            release_date = date_match.group(1)
            rest = after_release[date_match.end():].strip()
        else:
            rest = after_release

        same_line_match = qty_price_pattern.search(rest)
        if same_line_match:
            quantity = int(same_line_match.group(1))
            unit_price = float(same_line_match.group(2).replace(",", "."))
        else:
            # Chercher qty/prix sur la ligne suivante
            if i < n:
                next_line = lines_list[i].strip()
                qty_price_match = qty_price_pattern.search(next_line)
                if qty_price_match:
                    quantity = int(qty_price_match.group(1))
                    unit_price = float(qty_price_match.group(2).replace(",", "."))
                    i += 1

        products.append({
            "name": full_name,
            "release_date": release_date if release_date else "N/A",
            "quantity": quantity,
            "unit_price_usd": round(unit_price, 2)
        })

    return products

# Exemple d'endpoint pour uploader un PDF et récupérer les produits
@app.route("/api/upload-invoice", methods=["POST"])
def upload_invoice():
    """
    Attendre un champ 'invoice_pdf' dans form-data.
    Retourne JSON contenant parsed_products, shipping_cost_usd, bank_transfer_fee_usd, etc.
    """
    if "invoice_pdf" not in request.files:
        return jsonify({"error": "Aucun fichier PDF fourni"}), 400

    f = request.files["invoice_pdf"]
    temp_path = "/tmp/" + f.filename
    f.save(temp_path)

    # Récupérer le texte ligne par ligne
    lines = get_full_text_lines(temp_path)

    # Extraire shipping fee et bank fee brut
    full_text = "\n".join(lines)
    shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
    bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)

    shipping_fee = float(shipping_match.group(1)) if shipping_match else 0.0
    bank_fee = float(bank_fee_match.group(1)) if bank_fee_match else 0.0

    # Extraire les produits
    parsed_products = parse_products_from_lines(lines)

    return jsonify({
        "filename": f.filename,
        "shipping_cost_usd": shipping_fee,
        "bank_transfer_fee_usd": bank_fee,
        "parsed_products": parsed_products,
        "message": "OK"
    })

# Pour lancer en local avec python app.py
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
