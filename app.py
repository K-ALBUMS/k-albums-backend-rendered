from flask import Flask, jsonify, request
from flask_cors import CORS
from PyPDF2 import PdfReader
import io
import re
import requests 
from bs4 import BeautifulSoup 
from urllib.parse import urljoin

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
        print(f"--- Traitement PDF : {file.filename} (Backend V12) ---")
        file_content_in_memory = io.BytesIO(file.read())
        reader = PdfReader(file_content_in_memory)
        full_text = "".join([page.extract_text() + "\n" for page in reader.pages if page.extract_text()])

        if not full_text.strip():
            print("Avertissement: Texte PDF vide ou non extractible.")
            full_text = "[Extraction texte PDF échouée]"

        print("--- TEXTE PDF (V12 début) ---"); print(full_text[:2000]); print("--- FIN TEXTE (Snippet) ---")

        shipping_cost, bank_fee = None, None
        parsed_products = []
        lines = full_text.split('\n')
        product_name_buffer = []
        in_product_section = False

        header_re = re.compile(r"^\s*Product\s+Quantity\s+Price\s+Total\s*$", re.IGNORECASE)
        release_data_re = re.compile(
            r"(?P<name_on_line>.*?)(?:Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+))"
        )
        release_only_re = re.compile(r"^\s*Release\s*:\s*(?P<date>\d{4}-\d{2}-\d{2})?\s*$")
        data_after_release_re = re.compile(
            r"^(?:(?:Size|Ver|Version|Type)\s*:\s*(?P<variation>.*?)\s*)?(?P<quantity>\d+)\s*\$(?P<unit_price>\d+\.\d+)\s*\$(?P<total_price>\d+\.\d+)\s*$",
            re.IGNORECASE
        )

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not in_product_section:
                if header_re.match(line):
                    in_product_section = True
                    product_name_buffer = []
                    print(f"DEBUG (V12): Entrée section produits: '{line}'")
                continue

            if header_re.match(line):
                product_name_buffer = []
                print(f"DEBUG (V12): Header répété: '{line}'")
                continue
            
            if line.lower().startswith("subtotal"):
                product_name_buffer = []
                in_product_section = False
                print(f"DEBUG (V12): Sortie section (Subtotal): '{line}'")
                break

            name_to_add, date_to_add, qty_to_add, price_to_add = "", "N/A", None, None
            
            match1 = release_data_re.match(line)
            if match1:
                name_on_line = match1.group("name_on_line").strip()
                buffered_name = " ".join(product_name_buffer).strip()
                name_to_add = buffered_name if buffered_name else name_on_line
                if buffered_name and name_on_line and name_on_line != buffered_name:
                    name_to_add = f"{buffered_name} {name_on_line}"
                if name_to_add:
                    date_to_add = match1.group("date") or "N/A"
                    qty_to_add = match1.group("quantity")
                    price_to_add = match1.group("unit_price")
                    print(f"DEBUG (V12): Cas 1 (Nom+Release sur ligne) - Nom: '{name_to_add}'")
                else:
                    print(f"DEBUG (V12): Ligne Release Data SANS NOM clair: '{line}'")

            elif release_only_re.match(line):
                if (i < len(lines)):
                    next_line = lines[i].strip()
                    match_data_next = data_after_release_re.match(next_line)
                    if match_data_next:
                        name_from_buffer = " ".join(product_name_buffer).strip()
                        if name_from_buffer:
                            name_to_add = name_from_buffer
                            date_on_rl = release_only_re.match(line).group("date") or "N/A"
                            date_to_add = date_on_rl
                            variation = match_data_next.group("variation")
                            qty_to_add = match_data_next.group("quantity")
                            price_to_add = match_data_next.group("unit_price")
                            if variation:
                                name_to_add += f" ({variation.strip()})"
                            print(f"DEBUG (V12): Cas 2 (Release puis Data) - Nom: '{name_to_add}'")
                            i += 1
                        else:
                            print(f"DEBUG (V12): Release vide SANS NOM avant.")
                    else:
                        if line: product_name_buffer.append(line)
                else:
                    if line: product_name_buffer.append(line)

            elif line:
                product_name_buffer.append(line)

            if name_to_add and qty_to_add is not None and price_to_add is not None:
                final_name = header_re.sub("", name_to_add).strip()
                if final_name:
                    parsed_products.append({
                        "name": final_name,
                        "quantity": int(qty_to_add),
                        "unit_price_usd": float(price_to_add),
                        "release_date": date_to_add
                    })
                    print(f"  ==> PRODUIT AJOUTÉ (V12): {final_name} (Q:{qty_to_add} P:${price_to_add} D:{date_to_add})")
                else:
                    print(f"DEBUG (V12): Nom produit vide après nettoyage.")
                product_name_buffer = []

        if not parsed_products:
            print("Aucun produit n'a pu être parsé (V12).")
        else:
            print(f"{len(parsed_products)} produits parsés au total (V12).")

        shipping_match = re.search(r"Shipping\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if shipping_match:
            shipping_cost = shipping_match.group(1)
            print(f"Frais port (globaux): ${shipping_cost}")
        bank_fee_match = re.search(r"Bank transfer fee\s*\$?\s*(\d+\.?\d*)", full_text, re.IGNORECASE)
        if bank_fee_match:
            bank_fee = bank_fee_match.group(1)
            print(f"Frais bancaires (globaux): ${bank_fee}")

        return jsonify({
            "message": "Extraction produits (logique affinée V12), FDP et frais bancaires.",
            "filename": file.filename,
            "shipping_cost_usd": shipping_cost,
            "bank_transfer_fee_usd": bank_fee,
            "parsed_products": parsed_products,
            "DEVELOPMENT_full_text_for_debug": full_text
        })

    except Exception as e:
        print(f"Erreur critique lors du traitement du PDF : {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur interne majeure lors du traitement du PDF: {str(e)}"}), 500

    return jsonify({"error": "Un problème est survenu avec le fichier ou fichier non traité."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
