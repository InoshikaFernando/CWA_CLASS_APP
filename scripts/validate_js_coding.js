/*
 * validate_js_coding.js
 * =====================
 * Executes a reference solution for every ported JavaScript coding exercise
 * and diffs its real stdout against the stored `expected_output`, mirroring
 * the grader (coding/scoring.py evaluate_exercise_output: stdout === expected
 * after rstrip). Also re-evaluates every quiz snippet whose answer can be
 * computed, and checks the marked-correct answer matches.
 *
 * console.log is captured through Node's own util.format, so the captured text
 * is byte-identical to what real console.log would print (arrays, numbers,
 * booleans, etc.).
 *
 * Usage:
 *   node scripts/validate_js_coding.js
 * Exit code 0 = all green, 1 = at least one mismatch / missing solution.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const util = require('util');
const vm = require('vm');

const SPLIT_DIR = path.join(__dirname, '..', 'cwa_classroom', 'coding',
  'management', 'commands', 'upload_splits_js');

// Run `code` in a fresh sandbox, capturing console.log exactly as Node formats it.
function run(code) {
  const lines = [];
  const sandbox = {
    console: { log: (...a) => lines.push(util.format(...a)) },
    Math, JSON, Number, String, Boolean, Array, Object,
    parseInt, parseFloat, isNaN,
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { timeout: 2000 });
  return lines.join('\n');
}
const rstrip = (s) => String(s).replace(/\s+$/, '');

// ---- Reference solutions for write_code exercises, keyed by title ----------
const SOLUTIONS = {
  // Variables & Data Types — beginner
  'Hello, World!': `console.log("Hello, World!");`,
  'Store Your Name': `let name = "Test";\nconsole.log(\`Hello, \${name}!\`);`,
  'Variable: Store and Print a Name': `let name = "Ada";\nconsole.log(name);`,
  'Variable: Store a Number': `let age = 12;\nconsole.log(age);`,
  'Variable: A Decimal Number': `let price = 9.5;\nconsole.log(price);`,
  'Simple Math': `let x = 10, y = 3;\nconsole.log(x + y);\nconsole.log(x - y);\nconsole.log(x * y);\nconsole.log(x / y);`,
  'Variable: A Boolean': `let isStudent = true;\nconsole.log(isStudent);`,
  'Variable: Add Two Numbers': `let a = 3, b = 4;\nconsole.log(a + b);`,
  'Variable: Greeting String': `let name = "Sam";\nconsole.log("Hello, " + name);`,
  'Variable: Type of a Value': `let x = 5;\nconsole.log(typeof x);`,
  'Variable: Reassign': `let x = 10;\nx = 20;\nconsole.log(x);`,
  // Variables & Data Types — intermediate
  'Conversion: String to Number': `let s = "42";\nlet n = Number(s);\nconsole.log(n + 8);`,
  'Conversion: Number to String': `let age = 15;\nconsole.log("Age: " + String(age));`,
  'Type Inspector': `let age = 16;\nlet height = 1.75;\nlet city = "Auckland";\nlet isStudent = true;\nconsole.log(typeof age);\nconsole.log(typeof height);\nconsole.log(typeof city);\nconsole.log(typeof isStudent);`,
  'Conversion: Decimal to Integer': `let price = 9.8;\nconsole.log(Math.trunc(price));`,
  'Operator: Integer Division': `let a = 17, b = 5;\nconsole.log(Math.floor(a / b));`,
  'Operator: Modulo': `let a = 17, b = 5;\nconsole.log(a % b);`,
  'Temperature Converter': `let celsius = 25;\nconsole.log(\`\${celsius}°C is \${((celsius * 9/5) + 32).toFixed(1)}°F\`);`,
  'String Formatting: Template Literal': `let name = "Mia";\nlet score = 95;\nconsole.log(\`\${name} scored \${score}\`);`,
  'Multiple Assignment': `let [a, b, c] = [1, 2, 3];\nconsole.log(a + b + c);`,
  'Swap Two Variables': `let a = 1, b = 2;\n[a, b] = [b, a];\nconsole.log(\`a=\${a} b=\${b}\`);`,
  'Augmented Assignment': `let total = 10;\ntotal += 5;\nconsole.log(total);`,
  // Variables & Data Types — advanced (scope)
  'Type Casting': `let x = "42", y = "3.14";\nconsole.log(parseInt(x) + parseFloat(y));`,
  'Local Variable: Shadows Outer': `let x = 10;\nfunction show() { let x = 5; console.log(x); }\nshow();`,
  'Read an Outer Variable': `let counter = 42;\nfunction show() { console.log(counter); }\nshow();`,
  'Mutate an Outer Variable': `let count = 0;\nfunction increment() { count += 1; }\nincrement();\nincrement();\nconsole.log(count);`,
  'Scope Trap: Read the Outer Variable': `let value = 7;\nfunction show() { console.log(value); }\nshow();`,
  'Closure: Update an Enclosing Variable': `function outer() { let x = 1; function inner() { x = 99; } inner(); return x; }\nconsole.log(outer());`,
  'Mutability: Mutate an Array Argument': `let nums = [1, 2, 3];\nfunction modify(lst) { lst.push(99); }\nmodify(nums);\nconsole.log(JSON.stringify(nums));`,
  'Mutability: Reassigning vs Mutating': `let nums = [1, 2, 3];\nfunction rebind(lst) { lst = [9, 9, 9]; }\nrebind(nums);\nconsole.log(JSON.stringify(nums));`,
  'Numbers Are Passed by Value': `let n = 5;\nfunction change(x) { x = 100; }\nchange(n);\nconsole.log(n);`,
  // If Conditions — beginner
  'Positive or Negative': `let number = 7;\nif (number > 0) { console.log("Positive"); } else { console.log("Negative"); }`,
  'If: Positive Number': `let num = 7;\nif (num > 0) { console.log("Positive"); }`,
  'If: Is Even': `let num = 4;\nif (num % 2 === 0) { console.log("Even"); }`,
  'Even or Odd': `let number = 17;\nif (number % 2 === 0) { console.log("Even"); } else { console.log("Odd"); }`,
  'If: Big Enough': `let age = 21;\nif (age >= 18) { console.log("Adult"); }`,
  'If: Exact Match': `let colour = "red";\nif (colour === "red") { console.log("Stop"); }`,
  'If: Passing Mark': `let score = 72;\nif (score >= 50) { console.log("Pass"); }`,
  'If: Empty Array': `let items = [];\nif (items.length === 0) { console.log("Empty"); }`,
  'If: Member Check': `let word = "banana";\nif (word.includes("a")) { console.log("Found"); }`,
  'If: Boolean Flag': `let isRaining = true;\nif (isRaining) { console.log("Take an umbrella"); }`,
  // If Conditions — intermediate
  'If/Else: Even or Odd': `let num = 7;\nif (num % 2 === 0) { console.log("Even"); } else { console.log("Odd"); }`,
  'Grade Calculator': `let score = 72;\nif (score >= 90) console.log("A");\nelse if (score >= 80) console.log("B");\nelse if (score >= 70) console.log("C");\nelse if (score >= 60) console.log("D");\nelse console.log("F");`,
  'If/Else: Adult or Minor': `let age = 16;\nif (age >= 18) { console.log("Adult"); } else { console.log("Minor"); }`,
  'If/Else: Larger Number': `let a = 12, b = 9;\nif (a > b) { console.log(a); } else { console.log(b); }`,
  'Number Range Check': `let number = 42;\nif (number >= 1 && number <= 100) { console.log("In range"); } else { console.log("Out of range"); }`,
  'If/Else: Positive or Non-Positive': `let num = -3;\nif (num > 0) { console.log("Positive"); } else { console.log("Non-positive"); }`,
  'If/Else If/Else: Sign of a Number': `let num = 0;\nif (num > 0) console.log("Positive");\nelse if (num < 0) console.log("Negative");\nelse console.log("Zero");`,
  'If/Else If/Else: Grade Letter': `let score = 75;\nif (score >= 90) console.log("A");\nelse if (score >= 75) console.log("B");\nelse if (score >= 50) console.log("C");\nelse console.log("F");`,
  'If/Else with AND: In Range': `let x = 15;\nif (x >= 10 && x <= 20) { console.log("In range"); } else { console.log("Out of range"); }`,
  'If/Else with OR: Weekend': `let day = "Sun";\nif (day === "Sat" || day === "Sun") { console.log("Weekend"); } else { console.log("Weekday"); }`,
  // If Conditions — advanced (nested)
  'Nested If: Admin Panel': `let loggedIn = true, isAdmin = true;\nif (loggedIn) { if (isAdmin) { console.log("Admin panel"); } }`,
  'Nested If: Positive and Even': `let num = 8;\nif (num > 0) { if (num % 2 === 0) { console.log("Positive even"); } else { console.log("Positive odd"); } }`,
  'Nested If: Login Flow': `let username = "admin", password = "secret";\nif (username === "admin") { if (password === "secret") { console.log("Welcome admin"); } else { console.log("Access denied"); } } else { console.log("Access denied"); }`,
  'Nested If: Ticket Pricing': `let age = 30, isMember = true;\nif (age >= 18) { if (isMember) console.log(10); else console.log(15); } else { if (isMember) console.log(5); else console.log(7); }`,
  'Nested If: Triangle Classifier': `let a = 5, b = 5, c = 5;\nif (a + b > c && a + c > b && b + c > a) { if (a === b && b === c) { console.log("Equilateral"); } else { if (a === b || b === c || a === c) console.log("Isosceles"); else console.log("Scalene"); } } else { console.log("Not a triangle"); }`,
  'Nested If: Leap Year': `let year = 2000;\nif (year % 4 === 0) { if (year % 100 === 0) { if (year % 400 === 0) console.log("Leap"); else console.log("Not leap"); } else { console.log("Leap"); } } else { console.log("Not leap"); }`,
  'Leap Year': `let year = 2024;\nif ((year % 4 === 0 && year % 100 !== 0) || year % 400 === 0) { console.log("Leap year"); } else { console.log("Not a leap year"); }`,
  // Loops — beginner
  'Count to 5': `for (let i = 1; i <= 5; i++) console.log(i);`,
  'For Loop: Print 1-10': `for (let i = 1; i <= 10; i++) console.log(i);`,
  'For Loop: Even Numbers': `for (let i = 2; i <= 10; i += 2) console.log(i);`,
  'For Loop: Sum 1 to 5': `let total = 0;\nfor (let i = 1; i <= 5; i++) total += i;\nconsole.log(total);`,
  'Multiply Table': `for (let i = 1; i <= 10; i++) console.log(\`5 x \${i} = \${5 * i}\`);`,
  'For Loop: Multiplication Table': `for (let i = 1; i <= 5; i++) console.log(\`3 x \${i} = \${3 * i}\`);`,
  'While Loop: Countdown from 10': `let count = 10;\nwhile (count > 0) { console.log(count); count--; }`,
  'While Loop: Double Until 100': `let num = 1;\nwhile (num < 100) { console.log(num); num = num * 2; }`,
  'For...of: Loop Through an Array': `let fruits = ["apple", "banana", "cherry"];\nfor (let fruit of fruits) console.log(fruit);`,
  'For Loop: Count Vowels': `let word = "education";\nlet vowels = "aeiou";\nlet count = 0;\nfor (let letter of word) { if (vowels.includes(letter)) count++; }\nconsole.log(count);`,
  'While Loop: Sum Until 50': `let total = 0, n = 1;\nwhile (total < 50) { total += n; n++; }\nconsole.log(total);`,
  'For Loop: Reverse Countdown': `for (let i = 5; i >= 1; i--) console.log(i);`,
  'Nested Loop: Square Pattern': `for (let i = 0; i < 3; i++) { let row = ""; for (let j = 0; j < 3; j++) row += "*"; console.log(row); }`,
  'For Loop: Find Maximum': `let numbers = [4, 7, 2, 9, 5, 1];\nlet largest = numbers[0];\nfor (let num of numbers) { if (num > largest) largest = num; }\nconsole.log(largest);`,
  // Loops — intermediate
  'Sum of an Array': `let numbers = [4, 8, 15, 16, 23, 42];\nlet total = 0;\nfor (let n of numbers) total += n;\nconsole.log(total);`,
  'Countdown Loop': `for (let i = 10; i >= 1; i--) console.log(i);`,
  // Loops — advanced
  'FizzBuzz': `for (let i = 1; i <= 20; i++) { if (i % 15 === 0) console.log("FizzBuzz"); else if (i % 3 === 0) console.log("Fizz"); else if (i % 5 === 0) console.log("Buzz"); else console.log(i); }`,
  // Functions
  'Greet Function': `function greet(name) { console.log(\`Hello, \${name}!\`); }\ngreet("Alex");`,
  'Add Function': `function add(a, b) { return a + b; }\nconsole.log(add(15, 27));`,
  'Square Function': `function square(n) { return n * n; }\nconsole.log(square(9));`,
  'Check Prime': `function isPrime(n) { if (n < 2) return false; for (let i = 2; i < n; i++) if (n % i === 0) return false; return true; }\nconsole.log(isPrime(7));\nconsole.log(isPrime(10));`,
  'Factorial': `function factorial(n) { if (n === 0) return 1; return n * factorial(n - 1); }\nconsole.log(factorial(5));`,
  // Arrays
  'Create and Print an Array': `let fruits = ["apple", "banana", "cherry", "date", "elder"];\nconsole.log(JSON.stringify(fruits));`,
  'Access Array Elements': `let numbers = [10, 20, 30, 40, 50];\nconsole.log(numbers[0]);\nconsole.log(numbers[2]);\nconsole.log(numbers[numbers.length - 1]);`,
  'Array Length and Sum': `let scores = [85, 92, 78, 95, 88];\nconsole.log(scores.length);\nconsole.log(scores.reduce((a, b) => a + b, 0));`,
  'Double Each Item': `let numbers = [1, 2, 3, 4, 5];\nconsole.log(JSON.stringify(numbers.map(x => x * 2)));`,
  'Filter Even Numbers': `let numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];\nconsole.log(JSON.stringify(numbers.filter(x => x % 2 === 0)));`,
  // Strings
  'String Length': `let text = "Hello World";\nconsole.log(text.length);`,
  'String Uppercase and Lowercase': `let word = "JavaScript";\nconsole.log(word.toUpperCase());\nconsole.log(word.toLowerCase());`,
  'String Replace': `let sentence = "I love cats";\nconsole.log(sentence.replace("cats", "dogs"));`,
  'String Split and Join': `let text = "apple,banana,cherry";\nfor (let fruit of text.split(",")) console.log(fruit);`,
};

// ---- Quiz snippets whose marked-correct answer can be computed -------------
// title -> code that prints the value the correct answer should equal.
const QUIZ_EVAL = {
  'What is the output of:\nfor (let i = 0; i < 3; i++) {\n  console.log(i);\n}':
    `for (let i = 0; i < 3; i++) console.log(i);`,
  'What is the output of:\nlet total = 0;\nfor (const n of [1, 2, 3, 4]) {\n  total += n;\n}\nconsole.log(total);':
    `let total = 0; for (const n of [1, 2, 3, 4]) total += n; console.log(total);`,
  'What is the output of:\nfor (let i = 0; i < 3; i++) {\n  if (i === 1) break;\n  console.log(i);\n}':
    `for (let i = 0; i < 3; i++) { if (i === 1) break; console.log(i); }`,
  'What is the output of:\nfor (let i = 0; i < 4; i++) {\n  if (i === 2) continue;\n  console.log(i);\n}':
    `for (let i = 0; i < 4; i++) { if (i === 2) continue; console.log(i); }`,
  'What is the output of [3, 1, 2].sort((a, b) => b - a)?':
    `console.log(JSON.stringify([3, 1, 2].sort((a, b) => b - a)).replace(/,/g, ", "));`,
};

// ---------------------------------------------------------------------------
function loadExercises() {
  const out = [];
  for (const f of fs.readdirSync(SPLIT_DIR).filter(n => n.endsWith('.json')).sort()) {
    const data = JSON.parse(fs.readFileSync(path.join(SPLIT_DIR, f), 'utf8'));
    for (const ex of data.exercises) out.push({ file: f, ...ex });
  }
  return out;
}

function main() {
  const exercises = loadExercises();
  let pass = 0, fail = 0, missing = 0, manual = 0;
  const problems = [];

  for (const ex of exercises) {
    const qt = ex.question_type || 'write_code';
    if (qt === 'write_code') {
      const sol = SOLUTIONS[ex.title];
      if (sol === undefined) { missing++; problems.push(`MISSING solution: ${ex.title}`); continue; }
      let actual;
      try { actual = run(sol); }
      catch (e) { fail++; problems.push(`ERROR running "${ex.title}": ${e.message}`); continue; }
      if (rstrip(actual) === rstrip(ex.expected_output)) pass++;
      else { fail++; problems.push(`FAIL "${ex.title}"\n   expected: ${JSON.stringify(ex.expected_output)}\n   actual:   ${JSON.stringify(actual)}`); }
    } else if (qt === 'multiple_choice' || qt === 'true_false' || qt === 'short_answer' || qt === 'fill_blank') {
      const correct = (ex.answers || []).filter(a => a.is_correct).map(a => a.text);
      const expectedAns = qt === 'short_answer' || qt === 'fill_blank' ? ex.correct_short_answer : correct[0];
      const snippet = QUIZ_EVAL[ex.title];
      if (snippet) {
        const computed = rstrip(run(snippet));
        if (computed === rstrip(expectedAns)) pass++;
        else { fail++; problems.push(`QUIZ FAIL "${ex.title.split('\n')[0]}…"\n   marked correct: ${JSON.stringify(expectedAns)}\n   computed:       ${JSON.stringify(computed)}`); }
      } else {
        // Conceptual question — can't compute; just sanity-check structure.
        if (qt === 'multiple_choice' && correct.length !== 1) { fail++; problems.push(`STRUCT "${ex.title}": ${correct.length} correct answers`); }
        else if (qt === 'true_false' && correct.length !== 1) { fail++; problems.push(`STRUCT "${ex.title}": ${correct.length} correct`); }
        else manual++;
      }
    }
  }

  console.log(`\nValidated ${exercises.length} exercises`);
  console.log(`  PASS (executed):        ${pass}`);
  console.log(`  FAIL:                   ${fail}`);
  console.log(`  MISSING reference:      ${missing}`);
  console.log(`  Conceptual (eyeball):   ${manual}`);
  if (problems.length) {
    console.log('\n--- Issues ---');
    for (const p of problems) console.log(p);
  } else {
    console.log('\nAll executable exercises match their expected_output. ✔');
  }
  process.exit(fail || missing ? 1 : 0);
}

main();
