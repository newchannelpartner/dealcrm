import re

with open('index.html', 'r') as f:
    content = f.read()

original = content

# Fix 1: itemsObject.entries(DEAL_TYPE_LABELS).map(function(e) -> items.map(function(t)
# This one was already fixed by sed, confirm
# Let me check
if 'itemsObject.entries(DEAL_TYPE_LABELS)' in content:
    print("Fix1: itemsObject.entries still present - needs fix")
else:
    print("Fix1: Already fixed")

# Fix 2: (c.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')
# Should be: (c.tags || []).map(function(t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')
old2 = '''(c.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
new2 = '''(c.tags || []).map(function(t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
if old2 in content:
    content = content.replace(old2, new2)
    print("Fix2: Applied (contact table tags)")
else:
    print("Fix2: Pattern not found, checking...")
    # Try to find what's actually there
    if 'Object.entries(DEAL_TYPE_LABELS)' in content:
        for i, line in enumerate(content.split('\n')):
            if 'Object.entries(DEAL_TYPE_LABELS)' in line and 'c.tags' in line:
                print(f"  Found at line {i+1}: {line[:120]}")

# Fix 3: (contact.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')
old3 = '''(contact.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
new3 = '''(contact.tags || []).map(function(t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
if old3 in content:
    content = content.replace(old3, new3)
    print("Fix3: Applied (contact detail tags)")
else:
    print("Fix3: Pattern not found")

# Fix 4: openTodosObject.entries(DEAL_TYPE_LABELS).map(function(e) -> openTodos.map(function(t)
old4 = 'openTodosObject.entries(DEAL_TYPE_LABELS).map(function(e)'
new4 = 'openTodos.map(function(t)'
count4 = content.count(old4)
if count4 > 0:
    content = content.replace(old4, new4)
    print(f"Fix4: Applied ({count4} occurrences)")
else:
    print("Fix4: Pattern not found")

# Fix 5: TAGSObject.entries(DEAL_TYPE_LABELS).map(function(e) -> TAGS.map(function(t)
old5 = '''TAGSObject.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag-option" data-tag="' + t + '" onclick="toggleTag(this)">' + t + '</span>'; }).join('')'''
new5 = '''TAGS.map(function(t) { return '<span class="tag-option" data-tag="' + t + '" onclick="toggleTag(this)">' + t + '</span>'; }).join('')'''
if old5 in content:
    content = content.replace(old5, new5)
    print("Fix5: Applied (TAGS in contact modal)")
else:
    print("Fix5: Pattern not found, checking...")
    # Check what the line actually looks like
    for i, line in enumerate(content.split('\n')):
        if 'TAGS' in line and 'DEAL_TYPE_LABELS' in line:
            print(f"  Found at line {i+1}: {line[:120]}")

# Fix 6: deal type badge in detail panel - use DEAL_TYPE_LABELS
old6 = "'<span class=\"type-badge\">' + deal.type + '</span>'"
new6 = "'<span class=\"type-badge\">' + (DEAL_TYPE_LABELS[deal.type] || deal.type) + '</span>'"
count6 = content.count(old6)
if count6 > 0:
    content = content.replace(old6, new6)
    print(f"Fix6: Applied ({count6} occurrences)")
else:
    print("Fix6: Pattern not found")

# Fix 7: (deal.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) -> (deal.tags || []).map(function(t)
old7 = '''(deal.tags || [])Object.entries(DEAL_TYPE_LABELS).map(function(e) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
new7 = '''(deal.tags || []).map(function(t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('')'''
if old7 in content:
    content = content.replace(old7, new7)
    print("Fix7: Applied (deal detail tags)")
else:
    print("Fix7: Pattern not found")

# Fix 8: DEAL_TYPE_LABELSObject.entries(DEAL_TYPE_LABELS).map(...) -> Object.entries(DEAL_TYPE_LABELS).map(...)
old8 = 'DEAL_TYPE_LABELSObject.entries(DEAL_TYPE_LABELS).map(function(e)'
new8 = 'Object.entries(DEAL_TYPE_LABELS).map(function(e)'
count8 = content.count(old8)
if count8 > 0:
    content = content.replace(old8, new8)
    print(f"Fix8: Applied ({count8} occurrences)")
else:
    print("Fix8: Pattern not found")

if content != original:
    with open('index.html', 'w') as f:
        f.write(content)
    print("\nFixes applied and written.")
else:
    print("\nNo changes made.")

# Final check - count remaining issues
remaining = []
if 'Object.entries(DEAL_TYPE_LABELS)' in content:
    for i, line in enumerate(content.split('\n'), 1):
        if 'Object.entries(DEAL_TYPE_LABELS)' in line:
            remaining.append(f"  Line {i}: {line.strip()[:100]}")
if remaining:
    print(f"\nRemaining DEAL_TYPE_LABELS references ({len(remaining)}):")
    for r in remaining:
        print(r)

# Also verify no leftover broken patterns
for pat in ['itemsObject.', 'openTodosObject.', 'TAGSObject.', 'DEAL_TYPE_LABELSObject.']:
    if pat in content:
        print(f"WARNING: Still has '{pat}'")
