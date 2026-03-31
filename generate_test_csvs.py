"""
Generate test CSV files for CWA School App import testing.
Creates:
  - Sipsetha - Students.csv   (100 students across 6 classes with parent info)
  - Sipsetha - Teachers.csv   (teachers/staff)
  - Sipsetha - Balances.csv   (opening balances keyed by parent name)

Usage: python generate_test_csvs.py
"""

import csv
import random
import os
from datetime import date, timedelta

random.seed(42)

OUTPUT_DIR = os.path.join("cwa_classroom", "test_data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Name pools ---
FIRST_NAMES_M = [
    "Liam", "Noah", "Oliver", "James", "Ethan", "Lucas", "Mason", "Logan",
    "Alexander", "Henry", "Jacob", "Daniel", "Matthew", "Sebastian", "Jack",
    "Aiden", "Owen", "Samuel", "Ryan", "Nathan", "Leo", "Isaac", "Dylan",
    "Caleb", "Thomas", "Luke", "Gabriel", "Anthony", "Max", "Eli",
    "Jayden", "Joshua", "Andrew", "Lincoln", "Mateo", "Adrian", "Nolan",
    "Jordan", "Asher", "Cameron", "Connor", "Ezra", "Aaron", "Robert",
    "Hunter", "Dominic", "Cole", "Ian", "Adam", "Kai",
]

FIRST_NAMES_F = [
    "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte",
    "Amelia", "Harper", "Evelyn", "Abigail", "Emily", "Elizabeth", "Sofia",
    "Ella", "Madison", "Scarlett", "Victoria", "Aria", "Grace", "Chloe",
    "Camila", "Penelope", "Riley", "Layla", "Lillian", "Nora", "Zoey",
    "Hannah", "Lily", "Eleanor", "Hazel", "Violet", "Aurora", "Savannah",
    "Audrey", "Brooklyn", "Bella", "Claire", "Skylar", "Lucy", "Paisley",
    "Anna", "Caroline", "Maya", "Naomi", "Aaliyah", "Elena", "Sarah", "Zoe",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Chen", "Kim", "Park", "Singh", "Patel",
    "Cohen", "Ali", "Khan", "Santos", "Silva",
]

PARENT_FIRST_M = [
    "Michael", "David", "Richard", "Joseph", "Charles", "Mark", "Steven",
    "Paul", "Kevin", "Brian", "George", "Edward", "Peter", "Frank", "Raymond",
]

PARENT_FIRST_F = [
    "Jennifer", "Linda", "Patricia", "Barbara", "Susan", "Jessica", "Sarah",
    "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra", "Ashley", "Dorothy",
]

REGIONS_AU = ["NSW", "VIC", "QLD", "SA", "WA", "TAS"]
RELATIONSHIPS = ["mother", "father", "guardian"]

# ============================================================
# 6 Fixed classes
# ============================================================
CLASSES = [
    {
        "class_name": "Year 5 Maths Monday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 5",
        "class_day": "Monday",
        "class_start_time": "09:00",
        "class_end_time": "10:00",
    },
    {
        "class_name": "Year 6 Maths Wednesday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 6",
        "class_day": "Wednesday",
        "class_start_time": "10:00",
        "class_end_time": "11:00",
    },
    {
        "class_name": "Year 7 Maths Tuesday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 7",
        "class_day": "Tuesday",
        "class_start_time": "14:00",
        "class_end_time": "15:00",
    },
    {
        "class_name": "Year 7 Maths Saturday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 7",
        "class_day": "Saturday",
        "class_start_time": "09:00",
        "class_end_time": "10:00",
    },
    {
        "class_name": "Year 8 Maths Thursday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 8",
        "class_day": "Thursday",
        "class_start_time": "15:00",
        "class_end_time": "16:00",
    },
    {
        "class_name": "Year 9 Maths Friday",
        "department": "Mathematics",
        "subject": "Mathematics",
        "level": "Year 9",
        "class_day": "Friday",
        "class_start_time": "16:00",
        "class_end_time": "17:00",
    },
]

# ============================================================
# Helpers
# ============================================================
def gen_phone():
    return f"04{random.randint(10000000, 99999999)}"

def gen_dob_for_level(level):
    """Generate age-appropriate DOB for the level."""
    year_num = int(level.replace("Year ", ""))
    # Approx age = year_num + 5
    age = year_num + 5
    today = date.today()
    base = today.replace(year=today.year - age)
    offset = random.randint(-180, 180)
    return (base + timedelta(days=offset)).strftime("%Y-%m-%d")

def gen_email(first, last, domain="example.com"):
    tag = random.randint(1, 999)
    return f"{first.lower()}.{last.lower()}{tag}@{domain}"


# ============================================================
# Teachers CSV (1 per class + principal + admin = 8)
# ============================================================
teachers = []
teachers.append({
    "first_name": "Sarah",
    "last_name": "Henderson",
    "email": "sarah.henderson@school.example.com",
    "phone": gen_phone(),
    "position": "Principal Teacher",
    "specialty": "Mathematics",
    "status": "Active",
    "type": "Teacher",
})
teachers.append({
    "first_name": "Mark",
    "last_name": "Stevens",
    "email": "mark.stevens@school.example.com",
    "phone": gen_phone(),
    "position": "Admin",
    "specialty": "",
    "status": "Active",
    "type": "Staff",
})

teacher_names_used = {("Sarah", "Henderson"), ("Mark", "Stevens")}
class_teachers = []
for i, cls in enumerate(CLASSES):
    fn = random.choice(PARENT_FIRST_M + PARENT_FIRST_F)
    ln = random.choice(LAST_NAMES)
    while (fn, ln) in teacher_names_used:
        ln = random.choice(LAST_NAMES)
    teacher_names_used.add((fn, ln))
    full = f"{fn} {ln}"
    class_teachers.append(full)
    teachers.append({
        "first_name": fn,
        "last_name": ln,
        "email": gen_email(fn, ln, "school.example.com"),
        "phone": gen_phone(),
        "position": "Senior Teacher" if i == 0 else "Junior Teacher",
        "specialty": "Mathematics",
        "status": "Active",
        "type": "Teacher",
    })

TEACHER_FIELDS = ["first_name", "last_name", "email", "phone", "position", "specialty", "status", "type"]
teacher_path = os.path.join(OUTPUT_DIR, "Sipsetha - Teachers.csv")
with open(teacher_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=TEACHER_FIELDS)
    w.writeheader()
    w.writerows(teachers)
print(f"Wrote {len(teachers)} teachers -> {teacher_path}")


# ============================================================
# Students CSV  (100 students across 6 classes)
# ============================================================
STUDENT_FIELDS = [
    "first_name", "last_name", "email", "date_of_birth", "country", "region",
    "department", "subject", "level", "class_name", "class_day",
    "class_start_time", "class_end_time", "teacher",
    "parent1_first_name", "parent1_last_name", "parent1_email",
    "parent1_phone", "parent1_relationship", "parent1_address",
    "parent1_city", "parent1_country",
    "parent2_first_name", "parent2_last_name", "parent2_email",
    "parent2_phone", "parent2_relationship", "parent2_address",
    "parent2_city", "parent2_country",
]

# Distribute 100 students across 6 classes: ~17 each, remainder to first classes
class_sizes = [17, 17, 17, 17, 16, 16]  # = 100
class_assignments = []
for ci, size in enumerate(class_sizes):
    class_assignments.extend([ci] * size)
random.shuffle(class_assignments)

students = []
used_student_names = set()
parent_records = {}

# Pre-generate families (some siblings share parents)
family_last_names = random.sample(LAST_NAMES, 30)
family_parents = {}
for fln in family_last_names:
    mom_fn = random.choice(PARENT_FIRST_F)
    dad_fn = random.choice(PARENT_FIRST_M)
    family_parents[fln] = {
        "p1_first": mom_fn,
        "p1_last": fln,
        "p1_email": gen_email(mom_fn, fln, "parent.example.com"),
        "p1_phone": gen_phone(),
        "p1_rel": "mother",
        "p1_address": f"{random.randint(1, 200)} {random.choice(['Oak', 'Elm', 'Pine', 'Maple', 'Cedar', 'Birch'])} Street",
        "p1_city": random.choice(["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"]),
        "p1_country": "Australia",
        "p2_first": dad_fn,
        "p2_last": fln,
        "p2_email": gen_email(dad_fn, fln, "parent.example.com"),
        "p2_phone": gen_phone(),
        "p2_rel": "father",
    }

# ~70 from families, ~30 individual
family_slots = []
for fln in family_last_names:
    num_kids = random.choice([1, 1, 2, 2, 3])
    for _ in range(num_kids):
        family_slots.append(fln)
random.shuffle(family_slots)
family_slots = family_slots[:70]

for i in range(100):
    ci = class_assignments[i]
    cls = CLASSES[ci]
    teacher = class_teachers[ci]

    if i < len(family_slots):
        ln = family_slots[i]
        parents = family_parents[ln]
    else:
        ln = random.choice(LAST_NAMES)
        mom_fn = random.choice(PARENT_FIRST_F)
        dad_fn = random.choice(PARENT_FIRST_M)
        parents = {
            "p1_first": mom_fn, "p1_last": ln,
            "p1_email": gen_email(mom_fn, ln, "parent.example.com"),
            "p1_phone": gen_phone(), "p1_rel": "mother",
            "p1_address": f"{random.randint(1, 200)} {random.choice(['Oak', 'Elm', 'Pine', 'Maple'])} Street",
            "p1_city": random.choice(["Sydney", "Melbourne", "Brisbane"]),
            "p1_country": "Australia",
            "p2_first": dad_fn, "p2_last": ln,
            "p2_email": gen_email(dad_fn, ln, "parent.example.com"),
            "p2_phone": gen_phone(), "p2_rel": "father",
        }

    fn = random.choice(FIRST_NAMES_M + FIRST_NAMES_F)
    while (fn, ln) in used_student_names:
        fn = random.choice(FIRST_NAMES_M + FIRST_NAMES_F)
    used_student_names.add((fn, ln))

    country = random.choice(["Australia", "Australia", "New Zealand"])
    region = random.choice(REGIONS_AU) if country == "Australia" else ""

    row = {
        "first_name": fn,
        "last_name": ln,
        "email": gen_email(fn, ln, "student.example.com"),
        "date_of_birth": gen_dob_for_level(cls["level"]),
        "country": country,
        "region": region,
        "department": cls["department"],
        "subject": cls["subject"],
        "level": cls["level"],
        "class_name": cls["class_name"],
        "class_day": cls["class_day"],
        "class_start_time": cls["class_start_time"],
        "class_end_time": cls["class_end_time"],
        "teacher": teacher,
        "parent1_first_name": parents["p1_first"],
        "parent1_last_name": parents["p1_last"],
        "parent1_email": parents["p1_email"],
        "parent1_phone": parents["p1_phone"],
        "parent1_relationship": parents["p1_rel"],
        "parent1_address": parents["p1_address"],
        "parent1_city": parents["p1_city"],
        "parent1_country": parents["p1_country"],
        "parent2_first_name": parents["p2_first"],
        "parent2_last_name": parents["p2_last"],
        "parent2_email": parents["p2_email"],
        "parent2_phone": parents["p2_phone"],
        "parent2_relationship": parents["p2_rel"],
        "parent2_address": parents.get("p1_address", ""),
        "parent2_city": parents.get("p1_city", ""),
        "parent2_country": parents.get("p1_country", "Australia"),
    }
    students.append(row)

    pkey = (parents["p1_first"], parents["p1_last"])
    if pkey not in parent_records:
        parent_records[pkey] = []
    parent_records[pkey].append(i)

student_path = os.path.join(OUTPUT_DIR, "Sipsetha - Students.csv")
with open(student_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=STUDENT_FIELDS)
    w.writeheader()
    w.writerows(students)
print(f"Wrote {len(students)} students -> {student_path}")

# Print class distribution
from collections import Counter
dist = Counter(s["class_name"] for s in students)
for name, count in sorted(dist.items()):
    print(f"  {name}: {count} students")


# ============================================================
# Balances CSV  (one row per unique parent)
# ============================================================
BALANCE_FIELDS = ["first_name", "last_name", "balance", "net_invoices", "net_payments", "status"]

balances = []
for (pfn, pln), _idxs in parent_records.items():
    bal = round(random.uniform(-500, 2000), 2)
    inv = round(random.uniform(500, 5000), 2)
    pay = round(inv - bal, 2)
    balances.append({
        "first_name": pfn,
        "last_name": pln,
        "balance": f"{bal:.2f}",
        "net_invoices": f"{inv:.2f}",
        "net_payments": f"{pay:.2f}",
        "status": "Active",
    })

balance_path = os.path.join(OUTPUT_DIR, "Sipsetha - Balances.csv")
with open(balance_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=BALANCE_FIELDS)
    w.writeheader()
    w.writerows(balances)
print(f"Wrote {len(balances)} balance rows -> {balance_path}")

print("\nDone! Files in:", OUTPUT_DIR)
