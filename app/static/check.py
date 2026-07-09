with open('index.html', 'r') as f:
    content = f.read()

checks = []
checks.append(('DOCTYPE', '<!DOCTYPE html>' in content))
checks.append(('Ends with </html>', content.strip().endswith('</html>')))
checks.append(('Script tags', '<script>' in content and '</script>' in content))
checks.append(('DEAL_TYPE_LABELS constant', 'const DEAL_TYPE_LABELS' in content))
checks.append(('DEAL_STAGES constant', 'const DEAL_STAGES' in content))
checks.append(('None (standalone) option', 'None (standalone)' in content))
checks.append(('value="none" for standalone', 'value="none"' in content))
checks.append(('Independent Sponsor label', 'Independent Sponsor' in content))
checks.append(('All deal type labels', 'Sell-Side' in content and 'Buy-Side' in content and 'Credit' in content))
checks.append(('Exactly one script block', content.count('<script') == 1 and content.count('</script>') == 1))
checks.append(('No advisory', 'advisory' not in content))

all_ok = True
for label, result in checks:
    mark = '✓' if result else '✗'
    print(f'{mark} {label}')
    if not result:
        all_ok = False

print(f'\nTotal lines: {content.count(chr(10)) + 1}')
print(f'All checks passed: {all_ok}')
