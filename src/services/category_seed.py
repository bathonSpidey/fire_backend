"""The starting set of categories. Everything here is editable in the app afterwards.

Each row: (key, label, group, flow, fixed, description, legacy_item_category)
- flow: "expense" or "income". Transfers and investments are not categories (see TxKind).
- fixed: counts as a fixed cost in the fixed-vs-variable ratio.
- description: what Claude reads to decide, so make it concrete.
- legacy_item_category: the coarse pantry category the Inventory pages still use.
"""

SEED: list[tuple[str, str, str, str, bool, str, str]] = [
    # ── Food ──
    ("groceries", "Groceries", "Food", "expense", False,
     "Everyday food from supermarkets and bakeries: fresh and packaged food, snacks, sweets, "
     "coffee/tea for home.", "Food"),
    ("beverages", "Beverages & alcohol", "Food", "expense", False,
     "Drinks bought to take home: water, juice, soda, beer, wine, spirits.", "Drinks"),
    ("eating_out", "Eating out & cafes", "Food", "expense", False,
     "Restaurants, cafes, bars, canteens: a sit-down or on-the-spot meal or drink.", "Food"),
    ("takeaway", "Takeaway & delivery", "Food", "expense", False,
     "Delivered or takeaway meals (Lieferando, Wolt, street food, kiosks).", "Food"),
    ("deposit", "Deposit (Pfand)", "Food", "expense", False,
     "Bottle/crate deposits (Pfand) and their refunds.", "Deposit"),
    # ── Transport ──
    ("fuel", "Fuel (petrol/diesel)", "Transport", "expense", False,
     "Petrol or diesel at fuel stations. Shop items bought there are categorised separately.", "Other"),
    ("ev_charging", "EV charging", "Transport", "expense", False,
     "Charging an electric car: public chargers, charging cards, e-mobility invoices.", "Other"),
    ("parking", "Parking", "Transport", "expense", False, "Parking garages, meters, parking apps.", "Other"),
    ("public_transport", "Public transport", "Transport", "expense", False,
     "Trains, buses, trams, Deutschlandticket, DB tickets for everyday travel.", "Other"),
    ("taxi", "Taxi & ride-hailing", "Transport", "expense", False, "Taxi, Uber, Bolt, car sharing.", "Other"),
    ("car_costs", "Car costs", "Transport", "expense", True,
     "Car loan or lease, car insurance, road tax, repairs, tyres, tolls, car wash.", "Other"),
    # ── Health & body ──
    ("pharmacy", "Pharmacy & medicine", "Health & body", "expense", False,
     "Pharmacy purchases, medicine, vitamins, first aid.", "Medicine"),
    ("medical", "Doctor, dental & therapy", "Health & body", "expense", False,
     "Doctor, dentist, physio, therapy, glasses and other medical services.", "Medicine"),
    ("fitness", "Fitness & sports", "Health & body", "expense", True,
     "Gym membership, sports clubs, courses, sports activities.", "Other"),
    ("personal_care", "Personal care", "Health & body", "expense", False,
     "Hairdresser, cosmetics, skin care, shower and hygiene products from drugstores.", "Cosmetics"),
    # ── Home ──
    ("rent", "Rent & mortgage", "Home", "expense", True, "Rent, mortgage, service charges (Hausgeld).", "Living"),
    ("utilities", "Utilities", "Home", "expense", True,
     "Electricity, gas and heating, water, waste, broadcasting fee (Rundfunkbeitrag).", "Living"),
    ("internet_phone", "Internet & phone", "Home", "expense", True,
     "Internet, mobile and landline contracts.", "Living"),
    ("household_supplies", "Household supplies", "Home", "expense", False,
     "Cleaning products, paper goods, laundry, storage boxes, kitchenware, coasters.", "Living"),
    ("furniture_decor", "Furniture & decor", "Home", "expense", False,
     "Furniture, lamps, decoration, textiles, wall art, candles.", "Living"),
    ("diy_garden", "DIY & garden", "Home", "expense", False,
     "Tools, hardware, building materials, plants, planters, garden supplies.", "Hardware"),
    # ── Shopping ──
    ("clothing", "Clothing & shoes", "Shopping", "expense", False, "Clothes, shoes, accessories, bags.", "Clothing"),
    ("electronics", "Electronics & appliances", "Shopping", "expense", False,
     "Phones, computers, accessories, cables, appliances.", "Electronics"),
    ("books_media", "Books & media", "Shopping", "expense", False, "Books, magazines, music, films.", "Books"),
    ("gifts", "Gifts", "Shopping", "expense", False, "Presents for others, gift cards, gift wrap.", "Other"),
    ("pets", "Pets", "Shopping", "expense", False, "Pet food and treats, vet, litter, toys, supplies.", "Other"),
    ("shopping_general", "General shopping", "Shopping", "expense", False,
     "Retail purchases that fit no other category (e.g. an Amazon order with no receipt).", "Other"),
    # ── Leisure ──
    ("subscriptions", "Subscriptions & streaming", "Leisure", "expense", True,
     "Netflix, Spotify, apps, software and memberships billed regularly.", "Entertainment"),
    ("entertainment_events", "Events & entertainment", "Leisure", "expense", False,
     "Cinema, concerts, museums, theme parks, tickets.", "Entertainment"),
    ("hobbies", "Hobbies & games", "Leisure", "expense", False,
     "Hobby materials, games, crafts, sports equipment.", "Entertainment"),
    # ── Travel ──
    ("flights", "Flights", "Travel", "expense", False, "Airline tickets and airline fees.", "Travel"),
    ("accommodation", "Accommodation", "Travel", "expense", False, "Hotels, Airbnb, hostels, camping.", "Travel"),
    ("trip_spending", "Trip spending", "Travel", "expense", False,
     "Activities, local transport, souvenirs and other spending while travelling.", "Travel"),
    # ── Finance & admin ──
    ("insurance", "Insurance", "Finance & admin", "expense", True,
     "Liability, household, life, legal, travel insurance (not car insurance).", "Other"),
    ("loans", "Loans & financing", "Finance & admin", "expense", True,
     "Loan or financing instalments (non-car).", "Other"),
    ("taxes_fees", "Taxes, fees & fines", "Finance & admin", "expense", False,
     "Tax payments, court and authority fees, fines, official charges.", "Other"),
    ("bank_fees", "Bank & card fees", "Finance & admin", "expense", True,
     "Account and card fees, Entgeltabrechnung.", "Other"),
    ("education", "Education & courses", "Finance & admin", "expense", False,
     "Courses, tuition, training, exam fees.", "Work"),
    ("work_expenses", "Work expenses", "Finance & admin", "expense", False,
     "Work-related purchases and professional subscriptions.", "Work"),
    ("donations", "Donations & charity", "Finance & admin", "expense", False, "Donations and charity.", "Other"),
    ("remittances", "Remittances", "Finance & admin", "expense", False,
     "Money sent abroad or to family (Wise and similar).", "Other"),
    ("cash", "Cash withdrawals", "Finance & admin", "expense", False,
     "ATM withdrawals; counted as spending until it is known what the cash was for.", "Other"),
    ("other_expense", "Other", "Other", "expense", False, "Anything that fits nowhere else.", "Other"),
    # ── Income ──
    ("salary", "Salary", "Income", "income", False, "Salary and wages from an employer.", "Other"),
    ("tax_refund", "Tax refund", "Income", "income", False, "Refunds from the tax office.", "Other"),
    ("refunds_returns", "Refunds & returns", "Income", "income", False,
     "Money back from a merchant: returned goods, cancelled orders.", "Other"),
    ("interest_dividends", "Interest & dividends", "Income", "income", False,
     "Interest, dividends and investment income paid out.", "Other"),
    ("other_income", "Other income", "Income", "income", False,
     "Gifts received, reimbursements, sales, anything else coming in.", "Other"),
]

# Old coarse item category -> new default category (used once, to backfill existing receipt items).
LEGACY_ITEM_TO_KEY = {
    "Food": "groceries", "Drinks": "beverages", "Hardware": "diy_garden",
    "Electronics": "electronics", "Medicine": "pharmacy", "Entertainment": "entertainment_events",
    "Travel": "trip_spending", "Living": "household_supplies", "Work": "work_expenses",
    "Books": "books_media", "Clothing": "clothing", "Cosmetics": "personal_care",
    "Deposit": "deposit", "Other": "other_expense",
}

# Old regex-era bank categories -> new key. Ambiguous ones (FIXED_COSTS, TRAVEL, OTHER_EXPENSE)
# are left empty on purpose: the household can have Claude re-check them in one click.
LEGACY_BANK_TO_KEY = {
    "GROCERIES": "groceries", "DINING": "eating_out", "BENZIN": "fuel", "CHARGING": "ev_charging",
    "PARKING": "parking", "ONLINE_SHOPPING": "shopping_general", "SHOPPING": "shopping_general",
    "REMITTANCE": "remittances", "SALARY": "salary", "RETURNS": "refunds_returns",
    "OTHER_INCOME": "other_income",
}
