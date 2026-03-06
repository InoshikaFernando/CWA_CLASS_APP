"""
Migration 0031 — G8 Fractions.pdf (Year 8, 89 questions):
  Fractions (Y8): adding/subtracting, multiplying (whole × fraction, fraction × fraction,
                  mixed numbers), dividing (by whole, by fraction, mixed numbers),
                  word problems throughout.
All assigned to Year 8.
"""
from django.db import migrations

# ---------------------------------------------------------------------------
FRACTIONS_Y8 = [
    # ── Adding / Subtracting fractions ──────────────────────────────────────
    {
        "text": "Cody read 1/3 of a novel one day and 1/6 of the novel the next day. What fraction of the novel has he read in total?",
        "difficulty": 1,
        "answers": [
            ("1/2", True), ("2/9", False), ("1/3", False), ("3/9", False),
        ],
    },
    {
        "text": "Rosa wrote 1/2 of her book report on Tuesday and 1/5 on Wednesday. What fraction of her book report does she still have to write?",
        "difficulty": 2,
        "answers": [
            ("3/10", True), ("7/10", False), ("3/7", False), ("1/3", False),
        ],
    },
    {
        "text": "Calculate: 1/4 + 3/5",
        "difficulty": 1,
        "answers": [
            ("17/20", True), ("4/9", False), ("4/20", False), ("7/10", False),
        ],
    },
    {
        "text": "Calculate: 3/5 + 1/5",
        "difficulty": 1,
        "answers": [
            ("4/5", True), ("3/25", False), ("4/10", False), ("1/2", False),
        ],
    },
    {
        "text": "Calculate: 5/6 − 2/6",
        "difficulty": 1,
        "answers": [
            ("1/2", True), ("1/3", False), ("3/12", False), ("7/6", False),
        ],
    },
    {
        "text": "Calculate: 7/8 − 3/8",
        "difficulty": 1,
        "answers": [
            ("1/2", True), ("4/16", False), ("3/4", False), ("10/8", False),
        ],
    },

    # ── Whole number × fraction ──────────────────────────────────────────────
    {
        "text": "Maura pours 2/3 of a cup of water into a pot and repeats this 7 times. How many cups of water in total does she pour? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("4 2/3", True), ("3 2/3", False), ("14/7", False), ("5 1/3", False),
        ],
    },
    {
        "text": "Calculate: 5 × 3/4. Express as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("3 3/4", True), ("4 1/4", False), ("2 3/4", False), ("15/5", False),
        ],
    },
    {
        "text": "Calculate: 2 × 1/3",
        "difficulty": 1,
        "answers": [
            ("2/3", True), ("1/6", False), ("3/2", False), ("1/3", False),
        ],
    },
    {
        "text": "Calculate: 5 × 3/5",
        "difficulty": 1,
        "answers": [
            ("3", True), ("5/3", False), ("2", False), ("1/3", False),
        ],
    },
    {
        "text": "Calculate: 6 × 3/8. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("2 1/4", True), ("1 3/4", False), ("2 3/4", False), ("18/8", False),
        ],
    },
    {
        "text": "Calculate: 4 × 2/5. Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("1 3/5", True), ("2 2/5", False), ("8/20", False), ("1 2/5", False),
        ],
    },
    {
        "text": "Art class is 5/6 of an hour each school day. How many hours of art does a student have in five days? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("4 1/6", True), ("3 5/6", False), ("4 5/6", False), ("3 1/6", False),
        ],
    },
    {
        "text": "Devin needs 3/4 of a cup of flour to make one batch of bannock. How many cups of flour will he need to make six batches? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("4 1/2", True), ("3 3/4", False), ("5 1/4", False), ("4 3/4", False),
        ],
    },
    {
        "text": "At a party, 15 pitchers of lemonade are all filled to the same level. The lemonade is combined to fill exactly 6 whole pitchers. What fraction of each of the 15 pitchers was full?",
        "difficulty": 2,
        "answers": [
            ("2/5", True), ("3/5", False), ("1/3", False), ("5/9", False),
        ],
    },

    # ── Fraction × fraction (proper) ────────────────────────────────────────
    {
        "text": "About 1/10 of Canadians aged 12+ downhill ski. About 2/5 of those skiers are aged 12–24. What fraction of the Canadian population aged 12–24 are downhill skiers?",
        "difficulty": 2,
        "answers": [
            ("1/25", True), ("3/15", False), ("1/5", False), ("7/50", False),
        ],
    },
    {
        "text": "2/3 of the students in a school are in Grades 7 and 8. 5/8 of these students are girls. What fraction of all students in the school are girls in Grades 7 and 8?",
        "difficulty": 2,
        "answers": [
            ("5/12", True), ("7/11", False), ("1/4", False), ("3/8", False),
        ],
    },
    {
        "text": "Calculate: 1/2 × 3/8",
        "difficulty": 1,
        "answers": [
            ("3/16", True), ("4/10", False), ("5/8", False), ("3/8", False),
        ],
    },
    {
        "text": "Calculate: 4/5 × 1/3",
        "difficulty": 1,
        "answers": [
            ("4/15", True), ("5/15", False), ("4/8", False), ("7/15", False),
        ],
    },
    {
        "text": "Calculate: 1/6 × 2/5",
        "difficulty": 1,
        "answers": [
            ("1/15", True), ("3/30", False), ("3/11", False), ("2/11", False),
        ],
    },
    {
        "text": "Calculate: 3/4 × 2/6. Simplify your answer.",
        "difficulty": 1,
        "answers": [
            ("1/4", True), ("6/20", False), ("1/2", False), ("5/24", False),
        ],
    },
    {
        "text": "Ben's bed takes up 1/3 of the width and 3/5 of the length of his bedroom. What fraction of the floor area does the bed use up?",
        "difficulty": 2,
        "answers": [
            ("1/5", True), ("4/8", False), ("3/15", False), ("2/5", False),
        ],
    },
    {
        "text": "Jessica is awake for 2/3 of the day and spends 5/8 of that awake time at home. What fraction of the day is Jessica awake at home?",
        "difficulty": 2,
        "answers": [
            ("5/12", True), ("7/12", False), ("5/24", False), ("1/3", False),
        ],
    },
    {
        "text": "Jessica is awake at home for 5/12 of the day. How many hours per day is that? (There are 24 hours in a day.)",
        "difficulty": 2,
        "answers": [
            ("10 hours", True), ("12 hours", False), ("8 hours", False), ("6 hours", False),
        ],
    },
    {
        "text": "The Grade 8 class raised 2/5 of the total money for the school's archery program. The Grade 8 boys raised 2/3 of the Grade 8 money. What fraction of the whole money did the Grade 8 boys raise?",
        "difficulty": 2,
        "answers": [
            ("4/15", True), ("4/8", False), ("2/8", False), ("1/5", False),
        ],
    },
    {
        "text": "Cheyenne gets home after 4 p.m. on 1/2 of school days. She gets home after 5 p.m. on 2/5 of those days. On what fraction of school days does she get home after 5 p.m.?",
        "difficulty": 2,
        "answers": [
            ("1/5", True), ("3/10", False), ("7/10", False), ("2/7", False),
        ],
    },

    # ── Multiplying mixed numbers ────────────────────────────────────────────
    {
        "text": "A large bag of popcorn holds 2 1/2 times as much as a small bag. Aaron has 1 1/2 large bags. How many small bags' worth of popcorn does he have? Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("3 3/4", True), ("4 1/4", False), ("3 1/2", False), ("4 1/2", False),
        ],
    },
    {
        "text": "Maura is making 3 1/2 dozen cookies. If 2/7 of the cookies have icing, how many dozen cookies have icing?",
        "difficulty": 2,
        "answers": [
            ("1 dozen", True), ("1 1/2 dozen", False), ("2/7 dozen", False), ("7/2 dozen", False),
        ],
    },
    {
        "text": "Calculate: 2/3 × 2 1/4. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("1 1/2", True), ("2 1/12", False), ("1 1/3", False), ("4 1/2", False),
        ],
    },
    {
        "text": "Calculate: 1/2 × 2 5/8. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 5/16", True), ("1 3/8", False), ("1 1/2", False), ("2 5/16", False),
        ],
    },
    {
        "text": "Calculate: 2/3 × 2 1/5. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 7/15", True), ("1 2/5", False), ("2 7/15", False), ("1 4/15", False),
        ],
    },
    {
        "text": "Calculate: 1/4 × 2 1/3. Write as a fraction.",
        "difficulty": 2,
        "answers": [
            ("7/12", True), ("1/2", False), ("3/4", False), ("7/8", False),
        ],
    },
    {
        "text": "A smoothie recipe requires 1 1/4 cups of blueberries. How many cups do you need for 2 batches?",
        "difficulty": 1,
        "answers": [
            ("2 1/2", True), ("2 1/4", False), ("3", False), ("1 3/4", False),
        ],
    },
    {
        "text": "A smoothie recipe requires 1 1/4 cups of blueberries. How many cups do you need for 2 1/2 batches? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("3 1/8", True), ("3 3/4", False), ("2 7/8", False), ("3 1/4", False),
        ],
    },
    {
        "text": "A smoothie recipe requires 1 1/4 cups of blueberries. How many cups do you need for 3 1/3 batches? Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("4 1/6", True), ("3 3/4", False), ("4 1/4", False), ("5 1/12", False),
        ],
    },

    # ── Mid-chapter review ───────────────────────────────────────────────────
    {
        "text": "Calculate: 6 × 1/5. Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("1 1/5", True), ("6/5", False), ("1 4/5", False), ("2", False),
        ],
    },
    {
        "text": "Calculate: 8 × 3/5. Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("4 4/5", True), ("3 3/5", False), ("5 3/5", False), ("3/5", False),
        ],
    },
    {
        "text": "Calculate: 4 × 1 2/5. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("5 3/5", True), ("4 2/5", False), ("4 8/5", False), ("6 2/5", False),
        ],
    },
    {
        "text": "Calculate: 5 × 4/9. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("2 2/9", True), ("1 4/9", False), ("3 1/9", False), ("4/9", False),
        ],
    },
    {
        "text": "1/4 of 2/7 is:",
        "difficulty": 2,
        "answers": [
            ("1/14", True), ("3/11", False), ("1/7", False), ("2/7", False),
        ],
    },
    {
        "text": "___ of 4/5 is 3/5. Find the missing fraction.",
        "difficulty": 2,
        "answers": [
            ("3/4", True), ("4/3", False), ("12/25", False), ("3/5", False),
        ],
    },
    {
        "text": "About 3/4 of the traditional dancers in a First Nations school are girls. About 1/4 of these students are in Grade 8. What fraction of the students who dance are Grade 8 girls?",
        "difficulty": 2,
        "answers": [
            ("3/16", True), ("1/4", False), ("3/8", False), ("7/16", False),
        ],
    },
    {
        "text": "Calculate: 5/6 × 3/4. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("5/8", True), ("8/10", False), ("2/3", False), ("7/12", False),
        ],
    },
    {
        "text": "Calculate: 7/8 × 1/6",
        "difficulty": 2,
        "answers": [
            ("7/48", True), ("8/48", False), ("7/14", False), ("1/7", False),
        ],
    },
    {
        "text": "Calculate: 8/9 × 3/9. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("8/27", True), ("6/27", False), ("11/18", False), ("3/9", False),
        ],
    },
    {
        "text": "Calculate: 1 2/3 × 1 1/3. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("2 2/9", True), ("1 2/9", False), ("2 5/9", False), ("3 2/9", False),
        ],
    },
    {
        "text": "Calculate: 1 2/7 × 3. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("3 6/7", True), ("4 2/7", False), ("2 6/7", False), ("4 6/7", False),
        ],
    },
    {
        "text": "Calculate: 3/5 × 1 2/5",
        "difficulty": 2,
        "answers": [
            ("21/25", True), ("4/5", False), ("3/7", False), ("18/25", False),
        ],
    },

    # ── Dividing fraction by whole number ───────────────────────────────────
    {
        "text": "Maeve worked with a partner for 1/2 of her art classes. She had art class 9 out of 20 school days. For what fraction of school days did she work with a partner in art?",
        "difficulty": 2,
        "answers": [
            ("9/40", True), ("9/10", False), ("1/2", False), ("4/20", False),
        ],
    },
    {
        "text": "Two-thirds of a room still has to be tiled. Three workers share the job equally. What fraction of the room will each worker tile?",
        "difficulty": 2,
        "answers": [
            ("2/9", True), ("2/3", False), ("1/3", False), ("1/6", False),
        ],
    },
    {
        "text": "Calculate: 1/2 ÷ 4",
        "difficulty": 1,
        "answers": [
            ("1/8", True), ("2", False), ("1/4", False), ("4/2", False),
        ],
    },
    {
        "text": "Calculate: 8/9 ÷ 4",
        "difficulty": 1,
        "answers": [
            ("2/9", True), ("32/9", False), ("4/9", False), ("8/4", False),
        ],
    },
    {
        "text": "Calculate: 2/9 ÷ 4",
        "difficulty": 2,
        "answers": [
            ("1/18", True), ("8/9", False), ("2/36", False), ("1/9", False),
        ],
    },
    {
        "text": "Calculate: 6/9 ÷ 4. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("1/6", True), ("3/4", False), ("1/4", False), ("2/9", False),
        ],
    },
    {
        "text": "Calculate: 3/5 ÷ 6",
        "difficulty": 2,
        "answers": [
            ("1/10", True), ("18/5", False), ("3/30", False), ("3/11", False),
        ],
    },
    {
        "text": "Calculate: 2/3 ÷ 5",
        "difficulty": 2,
        "answers": [
            ("2/15", True), ("10/3", False), ("2/8", False), ("1/5", False),
        ],
    },
    {
        "text": "Calculate: 7/8 ÷ 3",
        "difficulty": 2,
        "answers": [
            ("7/24", True), ("21/8", False), ("7/11", False), ("3/8", False),
        ],
    },
    {
        "text": "Ken used 5/6 of a can of paint to cover four walls equally. How much of the can did he use for each wall?",
        "difficulty": 2,
        "answers": [
            ("5/24", True), ("5/6", False), ("5/4", False), ("1/6", False),
        ],
    },

    # ── Dividing fraction by fraction ────────────────────────────────────────
    {
        "text": "Kate needs 3/4 of a cup of berries. She only has a 1/3-cup measure. How many times must she fill the cup? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("2 1/4", True), ("1 3/4", False), ("3 1/3", False), ("1 1/4", False),
        ],
    },
    {
        "text": "Tom used 25 tiles to cover 1/5 of the floor. About how many more tiles does he need to finish the remaining 4/5?",
        "difficulty": 2,
        "answers": [
            ("100 tiles", True), ("125 tiles", False), ("75 tiles", False), ("80 tiles", False),
        ],
    },
    {
        "text": "Ben's fridge has 2 1/2 containers of orange juice. Each glass uses 1/5 of a container. How many full glasses can he pour?",
        "difficulty": 2,
        "answers": [
            ("12 glasses", True), ("10 glasses", False), ("15 glasses", False), ("8 glasses", False),
        ],
    },
    {
        "text": "Kane needs to measure 2 1/2 cups. How many times must he fill a 1/2-cup measure?",
        "difficulty": 1,
        "answers": [
            ("5 times", True), ("4 times", False), ("3 times", False), ("6 times", False),
        ],
    },
    {
        "text": "Calculate: 5 ÷ 1/3",
        "difficulty": 1,
        "answers": [
            ("15", True), ("5/3", False), ("3/5", False), ("1/15", False),
        ],
    },
    {
        "text": "Calculate: 5/6 ÷ 3/4. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 1/9", True), ("5/8", False), ("2 1/4", False), ("5/9", False),
        ],
    },
    {
        "text": "Calculate: 2 3/8 ÷ 1/2. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("4 3/4", True), ("1 3/16", False), ("3 3/4", False), ("5 1/4", False),
        ],
    },
    {
        "text": "Calculate: 5/6 ÷ 3/5. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 7/18", True), ("1/2", False), ("1 5/6", False), ("18/25", False),
        ],
    },
    {
        "text": "Steph writes 2/3 of a page per hour. At this rate, how long will she need to write 1 full page? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 1/2 hours", True), ("2/3 hours", False), ("1 hour", False), ("2 hours", False),
        ],
    },

    # ── Dividing with mixed numbers ──────────────────────────────────────────
    {
        "text": "Kylar's turkey takes 4 1/2 hours to cook. She checks it every 1/3 of an hour. How many times will she check the turkey before it is cooked?",
        "difficulty": 3,
        "answers": [
            ("13 times", True), ("9 times", False), ("15 times", False), ("18 times", False),
        ],
    },
    {
        "text": "Tim fills a 1/3-cup measure 5 times. How much flour has he measured altogether? Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("1 2/3 cups", True), ("1 1/2 cups", False), ("2 1/3 cups", False), ("1 1/3 cups", False),
        ],
    },
    {
        "text": "Tim needs to measure 2 3/8 cups of flour using only a 1/3-cup measure. How many times must he fill the measure? (Round up to the nearest whole number.)",
        "difficulty": 3,
        "answers": [
            ("8 times", True), ("6 times", False), ("7 times", False), ("9 times", False),
        ],
    },
    {
        "text": "Jane wants to pour 1 7/8 large cans of paint into small cans that each hold 3/5 as much as a large can. How many small cans will Jane fill? Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("3 1/8", True), ("2 3/5", False), ("4 1/5", False), ("2 1/8", False),
        ],
    },
    {
        "text": "Calculate: 2/9 ÷ 3/9. Simplify your answer.",
        "difficulty": 1,
        "answers": [
            ("2/3", True), ("6/81", False), ("3/2", False), ("2/9", False),
        ],
    },
    {
        "text": "Calculate: 1/3 ÷ 1/2",
        "difficulty": 1,
        "answers": [
            ("2/3", True), ("1/6", False), ("3/2", False), ("1/3", False),
        ],
    },
    {
        "text": "Calculate: 7/8 ÷ 4/8. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 3/4", True), ("5/4", False), ("28/32", False), ("2 1/4", False),
        ],
    },
    {
        "text": "Calculate: 2/3 ÷ 4/5",
        "difficulty": 2,
        "answers": [
            ("5/6", True), ("8/15", False), ("6/5", False), ("4/6", False),
        ],
    },
    {
        "text": "Calculate: 2/5 ÷ 1/5",
        "difficulty": 1,
        "answers": [
            ("2", True), ("2/25", False), ("1/2", False), ("4/5", False),
        ],
    },
    {
        "text": "Rebecca has 2/3 of a container of trail mix. Each snack pack uses 1/5 of a container. How many full snack packs can Rebecca make?",
        "difficulty": 2,
        "answers": [
            ("3", True), ("2", False), ("4", False), ("5", False),
        ],
    },
    {
        "text": "Calculate: 3/8 ÷ 9/8. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("1/3", True), ("27/64", False), ("8/3", False), ("3/9", False),
        ],
    },
    {
        "text": "Calculate: 5/6 ÷ 7/3. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("5/14", True), ("35/18", False), ("5/21", False), ("7/10", False),
        ],
    },
    {
        "text": "Calculate: 1 3/7 ÷ 2/3. Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("2 1/7", True), ("1 3/7", False), ("3 1/7", False), ("20/21", False),
        ],
    },
    {
        "text": "Annette filled 2 1/2 pitchers with 2/3 of the punch she made. How many pitchers would she fill if she used all the punch? Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("3 3/4", True), ("1 2/3", False), ("4 1/6", False), ("5", False),
        ],
    },
    {
        "text": "Devin takes 4 1/2 minutes to run one lap. How many laps can he do in 30 minutes? Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("6 2/3", True), ("5 1/2", False), ("7 1/3", False), ("13 1/2", False),
        ],
    },
    {
        "text": "A printer prints 20 pages in 1 1/2 minutes. How many pages per minute does it print? Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("13 1/3", True), ("10", False), ("30", False), ("12", False),
        ],
    },

    # ── Chapter review ───────────────────────────────────────────────────────
    {
        "text": "2/3 of 1/4 is:",
        "difficulty": 1,
        "answers": [
            ("1/6", True), ("2/7", False), ("3/8", False), ("1/3", False),
        ],
    },
    {
        "text": "1/2 of 6/9 is: (Simplify your answer.)",
        "difficulty": 1,
        "answers": [
            ("1/3", True), ("6/9", False), ("2/9", False), ("3/9", False),
        ],
    },
    {
        "text": "1 1/5 of 4/7 is: (Simplify your answer.)",
        "difficulty": 2,
        "answers": [
            ("24/35", True), ("4/7", False), ("6/7", False), ("4/35", False),
        ],
    },
    {
        "text": "Calculate: 5/8 × 3/5. Simplify your answer.",
        "difficulty": 1,
        "answers": [
            ("3/8", True), ("15/8", False), ("8/15", False), ("1/4", False),
        ],
    },
    {
        "text": "Calculate: 3/4 × 1 2/5. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("1 1/20", True), ("1 1/4", False), ("1 3/20", False), ("2 1/20", False),
        ],
    },
    {
        "text": "Calculate: 5/8 × 3/7",
        "difficulty": 2,
        "answers": [
            ("15/56", True), ("8/15", False), ("15/40", False), ("5/21", False),
        ],
    },
    {
        "text": "Calculate: 2/5 ÷ 4/5. Simplify your answer.",
        "difficulty": 1,
        "answers": [
            ("1/2", True), ("8/25", False), ("5/8", False), ("2/20", False),
        ],
    },
    {
        "text": "Calculate: 1/5 ÷ 5/8",
        "difficulty": 2,
        "answers": [
            ("8/25", True), ("5/40", False), ("1/40", False), ("5/8", False),
        ],
    },
    {
        "text": "Calculate: 5/8 ÷ 1/5. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("3 1/8", True), ("1/8", False), ("5/40", False), ("2 7/8", False),
        ],
    },
    {
        "text": "Calculate: 4 1/3 ÷ 1 1/2. Write as a mixed number.",
        "difficulty": 3,
        "answers": [
            ("2 8/9", True), ("3 1/9", False), ("6 1/2", False), ("2 2/9", False),
        ],
    },
    {
        "text": "Calculate: 8 × 4/5. Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("6 2/5", True), ("5 4/5", False), ("7 1/5", False), ("2/5", False),
        ],
    },
    {
        "text": "Calculate: 6 × 3/5. Write as a mixed number.",
        "difficulty": 1,
        "answers": [
            ("3 3/5", True), ("2 3/5", False), ("4 3/5", False), ("3/5", False),
        ],
    },
    {
        "text": "Calculate: 9 × 2/7. Write as a mixed number.",
        "difficulty": 2,
        "answers": [
            ("2 4/7", True), ("1 4/7", False), ("3 4/7", False), ("2/7", False),
        ],
    },
    {
        "text": "Calculate: 12 × 2/3",
        "difficulty": 1,
        "answers": [
            ("8", True), ("6", False), ("24/3", False), ("10", False),
        ],
    },
    {
        "text": "About 2/3 of students in Cody's school come by bus. About 1/3 of those students are on the bus for more than 1.5 hours each day. What fraction of all students are on the bus for more than 1.5 hours a day?",
        "difficulty": 2,
        "answers": [
            ("2/9", True), ("1/3", False), ("3/9", False), ("2/3", False),
        ],
    },
    {
        "text": "Phil used 2/3 of his sugar to make 3/4 of a batch of cookies. How much sugar would he have needed to make a whole batch?",
        "difficulty": 3,
        "answers": [
            ("8/9", True), ("1/2", False), ("9/8", False), ("2/3", False),
        ],
    },
    {
        "text": "Calculate: 10/9 ÷ 3",
        "difficulty": 2,
        "answers": [
            ("10/27", True), ("30/9", False), ("10/3", False), ("1/3", False),
        ],
    },
    {
        "text": "Calculate: 10/9 ÷ 2. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("5/9", True), ("20/9", False), ("4/9", False), ("2/9", False),
        ],
    },
    {
        "text": "Calculate: 4/5 ÷ 6. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("2/15", True), ("24/5", False), ("4/30", False), ("2/5", False),
        ],
    },
    {
        "text": "Calculate: 1/4 ÷ 5/8. Simplify your answer.",
        "difficulty": 2,
        "answers": [
            ("2/5", True), ("5/32", False), ("4/5", False), ("1/10", False),
        ],
    },
    {
        "text": "Calculate: 2/9 ÷ 3/8",
        "difficulty": 2,
        "answers": [
            ("16/27", True), ("6/72", False), ("27/16", False), ("6/17", False),
        ],
    },
    {
        "text": "Calculate: 3/4 ÷ 3 1/2. Simplify your answer.",
        "difficulty": 3,
        "answers": [
            ("3/14", True), ("21/8", False), ("1/14", False), ("3/7", False),
        ],
    },
]


# ---------------------------------------------------------------------------
def seed_data(apps, schema_editor):
    Topic    = apps.get_model('classroom', 'Topic')
    Subject  = apps.get_model('classroom', 'Subject')
    Level    = apps.get_model('classroom', 'Level')
    Question = apps.get_model('quiz', 'Question')
    Answer   = apps.get_model('quiz', 'Answer')

    maths = Subject.objects.get(slug='mathematics')
    year8 = Level.objects.filter(level_number=8).first()
    if not year8:
        return

    try:
        subtopic = Topic.objects.get(subject=maths, slug='fractions')
    except Topic.DoesNotExist:
        return

    subtopic.levels.add(year8)

    for q_data in FRACTIONS_Y8:
        q, created = Question.objects.get_or_create(
            topic=subtopic,
            level=year8,
            question_text=q_data['text'],
            defaults={
                'difficulty':    q_data['difficulty'],
                'question_type': 'multiple_choice',
            },
        )
        if created:
            for display_order, (ans_text, is_correct) in enumerate(q_data['answers'], start=1):
                Answer.objects.create(
                    question=q,
                    text=ans_text,
                    is_correct=is_correct,
                    display_order=display_order,
                )


def reverse_data(apps, schema_editor):
    Subject  = apps.get_model('classroom', 'Subject')
    Question = apps.get_model('quiz', 'Question')

    maths = Subject.objects.filter(slug='mathematics').first()
    if not maths:
        return

    all_texts = [q['text'] for q in FRACTIONS_Y8]
    Question.objects.filter(topic__subject=maths, question_text__in=all_texts).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0030_create_new_subtopics_and_seed'),
        ('quiz', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_data, reverse_data),
    ]
