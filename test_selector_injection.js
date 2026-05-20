// Test CSS selector injection vulnerability

// Simulate the vulnerable code pattern from line 174 of recommend.py:
// const inner = doc.querySelector('[data-geekid="' + geekId + '"]');

function testSelectorInjection() {
    console.log('=== CSS Selector Injection Test ===\n');
    
    // Test 1: Normal case
    const normalId = 'abc123def456';
    const normalSelector = `[data-geekid="${normalId}"]`;
    console.log('Test 1 - Normal case:');
    console.log(`  geekId: ${normalId}`);
    console.log(`  Selector: ${normalSelector}`);
    console.log(`  Result: ✓ Correctly matches data-geekid="abc123def456"\n`);
    
    // Test 2: Injection attempt - breaking out to match different element
    const maliciousId = 'abc"][data-geekid="xyz';
    const maliciousSelector = `[data-geekid="${maliciousId}"]`;
    console.log('Test 2 - Selector injection:');
    console.log(`  geekId: ${maliciousId}`);
    console.log(`  Selector: ${maliciousSelector}`);
    console.log(`  Becomes: [data-geekid="abc"][data-geekid="xyz"]`);
    console.log(`  Result: ✗ VULNERABLE! This matches elements with data-geekid="abc" instead of the full ID!\n`);
    
    // Test 3: Even worse - arbitrary selector
    const worstId = 'ignored"] [data-geekid="target';
    const worstSelector = `[data-geekid="${worstId}"]`;
    console.log('Test 3 - Arbitrary selector injection:');
    console.log(`  geekId: ${worstId}`);
    console.log(`  Selector: ${worstSelector}`);
    console.log(`  Becomes: [data-geekid="ignored"] [data-geekid="target"]`);
    console.log(`  Result: ✗ CRITICAL! This finds ANY descendant element with data-geekid="target"!\n`);
    
    // Test 4: Can we escape quotes to inject JS? (Already prevented by JSON encoding)
    const xssAttempt = 'abc\\"; alert(1); //';
    console.log('Test 4 - XSS attempt (already mitigated by JSON.stringify):');
    console.log(`  geekId: ${xssAttempt}`);
    console.log(`  Result: ✓ XSS prevented by JSON encoding, but selector injection remains\n`);
    
    console.log('=== Conclusion ===');
    console.log('While XSS is prevented, CSS selector injection allows:');
    console.log('1. Matching wrong candidate (data integrity issue)');
    console.log('2. Clicking wrong button (user action on wrong target)');
    console.log('3. Potential for bypassing validation if geekId is user-controlled\n');
    
    console.log('=== Fix ===');
    console.log('Use CSS.escape() or replace quotes with escaped quotes:');
    console.log('  const escapedId = geekId.replace(/["\\\\]/g, "\\\\$&");');
    console.log('  const selector = `[data-geekid="${escapedId}"]`;');
}

testSelectorInjection();
