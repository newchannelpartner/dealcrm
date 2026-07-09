with open('index.html', 'r') as f:
    content = f.read()

original = content

# Fix 1: loadNoteEntities - when type is empty, do nothing and hide dropdown
old1 = '''async function loadNoteEntities() {
  var type = document.getElementById('noteEntityType').value;
  var select = document.getElementById('noteEntityId');
  select.innerHTML = '<option value="">Select...</option>';
  try {
    if (type === 'contact') {
      var contacts = await api('/contacts');
      contacts.forEach(function(c) {
        var o = document.createElement('option');
        o.value = c.id; o.textContent = c.name; select.appendChild(o);
      });
    } else {
      var deals = await api('/deals');
      deals.forEach(function(d) {
        var o = document.createElement('option');
        o.value = d.id; o.textContent = d.name; select.appendChild(o);
      });
    }
  } catch (e) { console.error(e); }
}'''

new1 = '''async function loadNoteEntities() {
  var type = document.getElementById('noteEntityType').value;
  var select = document.getElementById('noteEntityId');
  select.innerHTML = '<option value="">Select...</option>';
  // Hide dropdown when None selected
  select.style.display = (type === '') ? 'none' : 'inline-block';
  if (!type) return;
  try {
    if (type === 'contact') {
      var contacts = await api('/contacts');
      contacts.forEach(function(c) {
        var o = document.createElement('option');
        o.value = c.id; o.textContent = c.name; select.appendChild(o);
      });
    } else {
      var deals = await api('/deals');
      deals.forEach(function(d) {
        var o = document.createElement('option');
        o.value = d.id; o.textContent = d.name; select.appendChild(o);
      });
    }
  } catch (e) { console.error(e); }
}'''

if old1 in content:
    content = content.replace(old1, new1)
    print('Fix1: Applied (loadNoteEntities none handling)')
else:
    print('Fix1: Pattern not found')
    # debug
    idx = content.find('function loadNoteEntities')
    if idx >= 0:
        print('  Found at offset', idx)
        print('  Content:', content[idx:idx+600])

# Fix 2: saveNote - send entity_type 'none' when empty, fix validation
old2 = '''  var entityType = document.getElementById('noteEntityType').value;
  var entityIdRaw = document.getElementById('noteEntityId').value;
  var entityId = entityIdRaw ? parseInt(entityIdRaw) : null;
  if (!entityId && entityType) { alert('Select a contact or deal'); return; }'''

new2 = '''  var entityType = document.getElementById('noteEntityType').value || 'none';
  var entityIdRaw = document.getElementById('noteEntityId').value;
  var entityId = entityIdRaw ? parseInt(entityIdRaw) : null;
  if (!entityId && entityType !== 'none') { alert('Select a contact or deal'); return; }'''

if old2 in content:
    content = content.replace(old2, new2)
    print('Fix2: Applied (saveNote none entity_type)')
else:
    print('Fix2: Pattern not found')

# Fix 3: note entity display - show "Standalone" for "none" type
old3 = "'<span class=\"note-entity\">' + esc(n.entity_type) + ' #' + (n.entity_id || '') + '</span>'"
new3 = "'<span class=\"note-entity\">' + (n.entity_type === 'none' ? 'Standalone' : esc(n.entity_type) + ' #' + (n.entity_id || '')) + '</span>'"

count3 = content.count(old3)
if count3 > 0:
    content = content.replace(old3, new3)
    print(f'Fix3: Applied ({count3} occurrences - note entity display)')
else:
    print('Fix3: Pattern not found')
    # Try alternate
    for i, line in enumerate(content.split('\n'), 1):
        if "note-entity" in line and "esc(n.entity_type)" in line:
            print(f'  Line {i}: {line.strip()[:120]}')

if content != original:
    with open('index.html', 'w') as f:
        f.write(content)
    print('\nFixes written.')
else:
    print('\nNo changes.')
