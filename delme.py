def calculate_total(price, quantity):
  """Calculates the total price including tax."""
  subtotal = price * quantity
  tax_rate = 0.1 # 10% tax
  tax_amount = subtotal * tax_rate
  total = subtotal + tax_amount
  return total

def process_order(item_price, item_quantity):
  """Processes a single order."""
  print(f"Processing order for item price {item_price} and quantity {item_quantity}")
  order_total = calculate_total(item_price, item_quantity)
  print(f"Order total: {order_total}")
  return order_total

if __name__ == "__main__":
  item1_price = 10
  item1_quantity = 5
  order1_total = process_order(item1_price, item1_quantity)

  item2_price = 25
  item2_quantity = 2
  order2_total = process_order(item2_price, item2_quantity)

  final_message = "Debugging complete!"
  print(final_message)