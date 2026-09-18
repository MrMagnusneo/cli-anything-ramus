#!/usr/bin/env bash
#
# Builds a complete two-level IDEF0 model of an order-fulfilment process and
# renders it, using only the CLI. Every diagram is drawn by Ramus itself.
#
#   export RAMUS_JAR=/path/to/ramus.jar
#   ./order_fulfilment.sh [output-directory]
#
set -euo pipefail

OUT="${1:-./order-fulfilment}"
CLI="${CLI:-cli-anything-ramus}"
P="$OUT/order-fulfilment.rsf"

mkdir -p "$OUT"

echo "==> Checking the Ramus backend"
"$CLI" doctor

echo "==> Creating the project"
"$CLI" project new "$P" \
    --model-name "Fulfil customer order" \
    --author "Analyst" \
    --project-name "Order fulfilment" \
    --definition "How a customer order becomes a delivery" \
    --classifier "Roles" \
    --classifier "Documents" \
    --overwrite

echo "==> Top-level activities"
for name in "Receive order" "Assemble goods" "Ship goods"; do
    "$CLI" --project "$P" function add "$name"
done

echo "==> Top-level flows"
# IDEF0 sides: input (left), control (top), mechanism (bottom), output (right)
"$CLI" --project "$P" arrow add --from border --from-side input \
    --to "Receive order"  --name "Customer order"
"$CLI" --project "$P" arrow add --from "Receive order" \
    --to "Assemble goods" --name "Confirmed order"
"$CLI" --project "$P" arrow add --from "Assemble goods" \
    --to "Ship goods"     --name "Packed goods"
"$CLI" --project "$P" arrow add --from "Ship goods" \
    --to border --to-side output --name "Delivered goods"
"$CLI" --project "$P" arrow add --from border --from-side control \
    --to "Assemble goods" --to-side control --name "Build specification"

echo "==> Decomposing 'Assemble goods' into its own diagram"
"$CLI" --project "$P" function decompose "Assemble goods" \
    "Pick parts" "Build unit" "Test unit"
"$CLI" --project "$P" arrow add --diagram "Assemble goods" \
    --from "Pick parts" --to "Build unit" --name "Parts"
"$CLI" --project "$P" arrow add --diagram "Assemble goods" \
    --from "Build unit" --to "Test unit" --name "Assembled unit"

echo "==> Reference data"
"$CLI" --project "$P" element add Roles "Order clerk"
"$CLI" --project "$P" element add Roles "Assembler"
"$CLI" --project "$P" element add Documents "Order form"

echo "==> The model"
"$CLI" --project "$P" model tree
"$CLI" --project "$P" arrow list

echo "==> Rendering"
"$CLI" --project "$P" export all "$OUT/diagrams" --overwrite
"$CLI" --project "$P" export pdf "$OUT/order-fulfilment.pdf" --overwrite

echo
echo "Done. Open $P in Ramus, or look at:"
find "$OUT" -type f \( -name '*.png' -o -name '*.pdf' \) | sort
