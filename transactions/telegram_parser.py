"""
Pure text parsing for the Telegram bot (no database access).

Turns free-form chat messages into transaction fields, e.g.

    250 groceries                 -> expense 250, category Groceries, today
    spent 1,200 on petrol yesterday
    +5000 salary                  -> income 5000, category Salary
    received 2.5k freelance 18/11
    ₹99 netflix 2026-11-18

Rules
-----
* amount: first token that looks like a number. Accepts ₹ / rs / inr, Indian or
  western thousands separators, up to 2 decimals and a "k" suffix (2.5k = 2500).
* type: "+" / income words -> income, "-" / spending words -> expense. Without
  an explicit word the matched category decides; otherwise it is an expense.
* date: today, yesterday, YYYY-MM-DD, DD/MM, DD-MM, DD/MM/YY(YY). Future dates
  are rejected (they are almost always typos).
* category: matched against the categories passed in (user's own first, then
  global defaults), by full name, by a word of the name, then by alias.
* description: whatever text is left.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Optional

INCOME = 'IN'
EXPENSE = 'EX'

MAX_TEXT_LENGTH = 500
MAX_AMOUNT = Decimal('9999999999.99')

INCOME_WORDS = {'income', 'earned', 'earn', 'received', 'receive', 'got', 'credit', 'credited'}
EXPENSE_WORDS = {'spent', 'spend', 'paid', 'pay', 'expense', 'bought', 'buy', 'debit', 'debited'}
CURRENCY_WORDS = {'rs', 'rs.', 'inr', '₹', 'rupees', 'rupee', '/-'}
FILLER_WORDS = {'on', 'for', 'at', 'in', 'of', 'to', 'from', 'via', 'the', 'a', 'an'}
# Words ignored when matching a category by one word of its name.
NAME_STOP_WORDS = {'and', 'other', '&'}

# Common words -> default category names (see transactions.models.DEFAULT_CATEGORIES).
ALIASES = {
    # Food & Dining
    'food': 'Food & Dining', 'lunch': 'Food & Dining', 'dinner': 'Food & Dining',
    'breakfast': 'Food & Dining', 'snacks': 'Food & Dining', 'snack': 'Food & Dining',
    'restaurant': 'Food & Dining', 'cafe': 'Food & Dining', 'coffee': 'Food & Dining',
    'tea': 'Food & Dining', 'swiggy': 'Food & Dining', 'zomato': 'Food & Dining',
    'pizza': 'Food & Dining', 'eating': 'Food & Dining',
    # Groceries
    'grocery': 'Groceries', 'vegetables': 'Groceries', 'veggies': 'Groceries',
    'fruits': 'Groceries', 'milk': 'Groceries', 'blinkit': 'Groceries',
    'zepto': 'Groceries', 'bigbasket': 'Groceries', 'kirana': 'Groceries',
    # Housing & Rent
    'rent': 'Housing & Rent', 'maintenance': 'Housing & Rent', 'house': 'Housing & Rent',
    # Utilities & Bills
    'electricity': 'Utilities & Bills', 'bill': 'Utilities & Bills', 'bills': 'Utilities & Bills',
    'wifi': 'Utilities & Bills', 'internet': 'Utilities & Bills', 'broadband': 'Utilities & Bills',
    'recharge': 'Utilities & Bills', 'mobile': 'Utilities & Bills', 'water': 'Utilities & Bills',
    'gas': 'Utilities & Bills',
    # Transportation & Fuel
    'fuel': 'Transportation & Fuel', 'petrol': 'Transportation & Fuel', 'diesel': 'Transportation & Fuel',
    'uber': 'Transportation & Fuel', 'ola': 'Transportation & Fuel', 'rapido': 'Transportation & Fuel',
    'cab': 'Transportation & Fuel', 'taxi': 'Transportation & Fuel', 'auto': 'Transportation & Fuel',
    'bus': 'Transportation & Fuel', 'metro': 'Transportation & Fuel', 'train': 'Transportation & Fuel',
    'parking': 'Transportation & Fuel', 'toll': 'Transportation & Fuel',
    # Healthcare & Fitness
    'doctor': 'Healthcare & Fitness', 'medicine': 'Healthcare & Fitness', 'medicines': 'Healthcare & Fitness',
    'pharmacy': 'Healthcare & Fitness', 'hospital': 'Healthcare & Fitness', 'gym': 'Healthcare & Fitness',
    'health': 'Healthcare & Fitness',
    # Entertainment & Leisure
    'movie': 'Entertainment & Leisure', 'movies': 'Entertainment & Leisure', 'netflix': 'Entertainment & Leisure',
    'spotify': 'Entertainment & Leisure', 'prime': 'Entertainment & Leisure', 'hotstar': 'Entertainment & Leisure',
    'games': 'Entertainment & Leisure', 'party': 'Entertainment & Leisure', 'concert': 'Entertainment & Leisure',
    # Shopping & Personal
    'clothes': 'Shopping & Personal', 'shoes': 'Shopping & Personal', 'amazon': 'Shopping & Personal',
    'flipkart': 'Shopping & Personal', 'myntra': 'Shopping & Personal', 'haircut': 'Shopping & Personal',
    'salon': 'Shopping & Personal',
    # Education & Learning
    'course': 'Education & Learning', 'books': 'Education & Learning', 'book': 'Education & Learning',
    'fees': 'Education & Learning', 'tuition': 'Education & Learning', 'udemy': 'Education & Learning',
    # Travel & Vacations
    'flight': 'Travel & Vacations', 'hotel': 'Travel & Vacations', 'trip': 'Travel & Vacations',
    'vacation': 'Travel & Vacations', 'holiday': 'Travel & Vacations',
    # Savings & Investments (expense side)
    'sip': 'Savings & Investments', 'mutual': 'Savings & Investments', 'stocks': 'Savings & Investments',
    'fd': 'Savings & Investments',
    # Income side
    'salary': 'Salary', 'paycheck': 'Salary', 'stipend': 'Salary',
    'freelance': 'Freelance & Consulting', 'consulting': 'Freelance & Consulting', 'client': 'Freelance & Consulting',
    'dividend': 'Investments & Dividends', 'dividends': 'Investments & Dividends', 'interest': 'Investments & Dividends',
    'gift': 'Gifts & Grants', 'gifts': 'Gifts & Grants', 'scholarship': 'Gifts & Grants',
    'business': 'Business Revenue', 'sales': 'Business Revenue',
}

_NUMBER_RE = re.compile(r'^\d[\d,]*(?:\.\d+)?k?$', re.IGNORECASE)
_ISO_DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
_DM_DATE_RE = re.compile(r'^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2}|\d{4}))?$')


class ParseError(ValueError):
    """Raised with a user-facing message when a message cannot be understood."""


@dataclass
class ParsedTransaction:
    amount: Decimal
    transaction_type: str          # 'IN' or 'EX' (resolved)
    category: Optional[object]     # a Category instance (or any object with name/category_type)
    date: date
    description: str
    explicit_type: bool            # True if the user said income/expense explicitly


def _strip_currency(token: str) -> str:
    t = token
    lower = t.lower()
    for prefix in ('₹', 'rs.', 'rs', 'inr'):
        if lower.startswith(prefix) and len(t) > len(prefix) and t[len(prefix)].isdigit():
            return t[len(prefix):]
    for suffix in ('/-', '₹', 'rs', 'inr'):
        if lower.endswith(suffix) and len(t) > len(suffix) and t[-len(suffix) - 1].isdigit():
            return t[:-len(suffix)]
    return t


def parse_amount_token(token: str) -> Optional[Decimal]:
    """Return a positive Decimal if the token is an amount, else None. Raises ParseError if invalid."""
    t = _strip_currency(token)
    if not _NUMBER_RE.match(t):
        return None
    multiplier = Decimal(1)
    if t[-1] in 'kK':
        multiplier = Decimal(1000)
        t = t[:-1]
    try:
        value = Decimal(t.replace(',', '')) * multiplier
    except InvalidOperation:
        return None
    if multiplier == 1 and value != value.quantize(Decimal('0.01')):
        raise ParseError('Amounts can have at most 2 decimal places.')
    value = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ParseError('The amount must be greater than zero.')
    if value > MAX_AMOUNT:
        raise ParseError('That amount is too large.')
    return value


def parse_date_token(token: str, today: date) -> Optional[date]:
    """Return a date if the token is a date expression, else None. Raises ParseError if invalid."""
    lower = token.lower()
    if lower == 'today':
        return today
    if lower in ('yesterday', 'yday'):
        return today - timedelta(days=1)
    try:
        m = _ISO_DATE_RE.match(token)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DM_DATE_RE.match(token)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            year = m.group(3)
            if year is None:
                result = date(today.year, month, day)
                # "28/12" sent in January means last December.
                return result if result <= today else date(today.year - 1, month, day)
            year = int(year)
            if year < 100:
                year += 2000
            return date(year, month, day)
    except ValueError:
        raise ParseError(f'"{token}" is not a valid date. Use DD/MM, DD/MM/YYYY or YYYY-MM-DD.')
    return None


def _name_words(name: str):
    return [w for w in re.split(r'[^a-z0-9]+', name.lower()) if w and w not in NAME_STOP_WORDS]


def _ordered_candidates(categories, explicit_type):
    """User's own categories first, then defaults; expenses before income when the type is open."""
    cands = [c for c in categories if explicit_type is None or c.category_type == explicit_type]
    return sorted(
        cands,
        key=lambda c: (
            getattr(c, 'user_id', None) is None,       # own categories first
            c.category_type != EXPENSE,                  # expense first if ambiguous
            c.name.lower(),
        ),
    )


def match_category(words, categories, explicit_type=None):
    """Pick the best category for the given lowercase words, or None."""
    cands = _ordered_candidates(categories, explicit_type)
    if not cands or not words:
        return None
    text = ' '.join(words)

    # 1. Full category name appears in the text ("food & dining", "groceries").
    for c in sorted(cands, key=lambda c: -len(c.name)):
        if re.search(r'(?<!\w)' + re.escape(c.name.lower()) + r'(?!\w)', text):
            return c

    # 2. A word matches a word of a category name ("food" -> "Food & Dining").
    for w in words:
        if len(w) < 3:
            continue
        for c in cands:
            for nw in _name_words(c.name):
                if w == nw or (len(w) >= 4 and len(nw) >= 4 and (nw.startswith(w) or w.startswith(nw))):
                    return c

    # 3. Alias ("swiggy" -> "Food & Dining").
    for w in words:
        target = ALIASES.get(w) or (ALIASES.get(w[:-1]) if w.endswith('s') else None)
        if not target:
            continue
        for c in cands:
            if c.name.lower() == target.lower():
                return c
    return None


def parse_transaction_text(text, categories: Iterable, today: date) -> ParsedTransaction:
    """Parse a free-text message. Raises ParseError with a friendly message on failure."""
    if not isinstance(text, str) or not text.strip():
        raise ParseError('Send an amount and what it was for, e.g. "250 groceries".')
    if len(text) > MAX_TEXT_LENGTH:
        raise ParseError(f'Message is too long (max {MAX_TEXT_LENGTH} characters).')

    tokens = text.split()
    explicit_type = None
    amount = None
    txn_date = None
    remaining = []

    for raw in tokens:
        token = raw.strip(',;:!?()[]"\'')
        if not token:
            continue
        lower = token.lower()

        if lower in INCOME_WORDS and explicit_type is None:
            explicit_type = INCOME
            continue
        if lower in EXPENSE_WORDS and explicit_type is None:
            explicit_type = EXPENSE
            continue
        if lower in CURRENCY_WORDS:
            continue

        if amount is None:
            sign = None
            body = token
            if body[:1] in '+-' and len(body) > 1:
                sign, body = body[0], body[1:]
            # Dates like 18/11 or 2026-11-18 are not amounts.
            if not (_ISO_DATE_RE.match(body) or _DM_DATE_RE.match(body)):
                parsed = parse_amount_token(body)
                if parsed is not None:
                    amount = parsed
                    if sign == '+' and explicit_type is None:
                        explicit_type = INCOME
                    elif sign == '-' and explicit_type is None:
                        explicit_type = EXPENSE
                    continue

        if txn_date is None:
            parsed_date = parse_date_token(token, today)
            if parsed_date is not None:
                txn_date = parsed_date
                continue

        remaining.append(token)

    if amount is None:
        raise ParseError('I couldn\'t find an amount. Try "250 groceries" or "+5000 salary".')

    txn_date = txn_date or today
    if txn_date > today:
        raise ParseError('The date is in the future. Use today, yesterday or a past date.')

    # Trim filler words from both ends of the description ("on groceries" -> "groceries").
    while remaining and remaining[0].lower() in FILLER_WORDS:
        remaining.pop(0)
    while remaining and remaining[-1].lower() in FILLER_WORDS:
        remaining.pop()

    words = [w.lower() for w in remaining]
    category = match_category(words, list(categories), explicit_type)

    if explicit_type:
        transaction_type = explicit_type
    elif category is not None:
        transaction_type = category.category_type
    else:
        transaction_type = EXPENSE

    return ParsedTransaction(
        amount=amount,
        transaction_type=transaction_type,
        category=category,
        date=txn_date,
        description=' '.join(remaining)[:500],
        explicit_type=explicit_type is not None,
    )


def format_inr(value) -> str:
    """Format a number as rupees with Indian digit grouping: 1250000 -> ₹12,50,000."""
    value = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    sign = '-' if value < 0 else ''
    whole, frac = f'{abs(value):.2f}'.split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r'(\d)(?=(\d{2})+$)', r'\1,', head)
        whole = f'{head},{tail}'
    return f'{sign}₹{whole}' + ('' if frac == '00' else f'.{frac}')
