# app.py

import os
import re
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import pdfplumber

app = Flask(__name__)
CORS(app)

# -------------------------------------------------------------
# utilitaire : lit toutes les pages et renvoie la liste de lignes
# -------------------------------------------------------------
def get_full_text_lines(file_path):
    """
    Ouvre le PDF via pdfplumber, extrait le texte page par page,
    puis retourne une liste de lignes nettoyées.
    """
    lines = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if not page_text:
                continue
            for raw_line in page_text.split("\n"):
                line = raw_line.strip()
                if line:
                    lines.append(line)
    return lines

# -------------------------------------------------------------
# fonction de parsing des lignes pour extraire la liste de produits
# -------------------------------------------------------------
def parse_products_from_lines(lines_list):
    """
    Parcourt lines_list (chaque élément est une ligne extraite du PDF),
    trouve la section "Product Quantity Price Total", l’analyse jusqu’à "Subtotal",
    et retourne une liste de dict {"name", "quantity", "unit_price_usd", "release_date"}.
    """

    products = []
    i = 0
    n = len(lines_list)

    # 1) Trouver le début de la section produits
    while i < n and "Product Quantity Price Total" not in lines_list[i]:
        i += 1
    if i >= n:
        return []

    # Passer la ligne d'en‐tête
    i += 1

    # Patterns regex
    date_pattern = re.compile(r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)")
    qty_price_pattern = re.compile(r"(\d+)\s*\$?([\d.,]+)")

    def is_subtotal_line(line):
        return line.strip().startswith("Subtotal")

    # 2) Parcourir jusqu'à "Subtotal"
    while i < n and not is_subtotal_line(lines_list[i]):
        # Accumuler le nom du produit (potentiellement multi‐lignes)
        name_lines = []
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

        # Valeurs par défaut
        release_date = "N/A"
        quantity = 0
        unit_price = 0.0

        # Extrait la partie après "Release :"
        after_release = release_line[len("Release :"):].strip()
        date_match = date_pattern.match(after_release)
        if date_match:
            release_date = date_match.group(1)
            rest = after_release[date_match.end():].strip()
        else:
            rest = after_release

        # On cherche quantité + prix unitaire sur la même ligne
        same_line_match = qty_price_pattern.search(rest)
        if same_line_match:
            quantity = int(same_line_match.group(1))
            # Remplacer la virgule par point s’il y en a
            unit_price = float(same_line_match.group(2).replace(",", "."))
        else:
            # Sinon, chercher sur la ligne suivante
            if i < n:
                next_line = lines_list[i].strip()
                qty_price_match = qty_price_pattern.search(next_line)
                if qty_price_match:
                    quantity = int(qty_price_match.group(1))
                    unit_price = float(qty_price_match.group(2).replace(",", "."))
                    i += 1  # Consommer cette ligne aussi

        products.append({
            "name": full_name,
            "release_date": release_date if release_date else "N/A",
            "quantity": quantity,
            "unit_price_usd": round(unit_price, 2)
        })

    return products

# -------------------------------------------------------------
# endpoint principal : upload de la facture PDF + parsing
# -------------------------------------------------------------
@app.route("/api/upload-invoice", methods=["POST"])
def upload_invoice():
    try:
        # 1) Vérifier qu'on a bien un fichier nommé 'invoice_pdf'
        if "invoice_pdf" not in request.files:
            return jsonify({"error": "Aucun fichier PDF fourni."}), 400

        f = request.files["invoice_pdf"]
        if f.filename == "":
            return jsonify({"error": "Nom de fichier vide."}), 400

        # 2) Sauvegarder temporairement le PDF dans /tmp
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        f.save(temp_path)

        # 3) Extraire toutes les lignes du PDF
        lines = get_full_text_lines(temp_path)

        # 4) Construire le texte complet pour rechercher shipping fee et bank fee
        full_text = "\n".join(lines)
        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)

        shipping_fee = float(shipping_match.group(1)) if shipping_match else 0.0
        bank_fee = float(bank_fee_match.group(1)) if bank_fee_match else 0.0

        # 5) Extraire la liste des produits
        parsed_products = parse_products_from_lines(lines)

        # 6) Nettoyer le fichier temporaire
        try:
            os.remove(temp_path)
        except Exception:
            pass

        return jsonify({
            "filename": f.filename,
            "shipping_cost_usd": shipping_fee,
            "bank_transfer_fee_usd": bank_fee,
            "parsed_products": parsed_products,
            "message": "OK"
        }), 200

    except Exception as e:
        # En cas d'erreur imprévue, on renvoie toujours un JSON d'erreur
        return jsonify({
            "error": "Une erreur interne est survenue lors du parsing du PDF.",
            "details": str(e)
        }), 500

# -------------------------------------------------------------
# Pour exécuter en local : python app.py
# -------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
