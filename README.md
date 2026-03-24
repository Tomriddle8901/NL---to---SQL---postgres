# NL-to-SQL for PostgreSQL 🚀

## 💡 Why I Built This

After learning PostgreSQL, I realized something interesting.

The same query can be written in **multiple valid ways**.  
And when you bring AI into the picture, things get even more complicated.

You can ask:

> “show students whose name starts with A and have orders greater than 5000”

And AI will give you an answer.

But then a question arises:

👉 **How do I know if that SQL is actually correct?**  
👉 **What if the query is interpreted differently?**  
👉 **What if PostgreSQL version changes behavior?**

Sometimes:
- the same English sentence has **multiple meanings**
- the same SQL logic can be written in **different forms**
- and LLMs may generate **invalid or hallucinated queries**

That’s where this project started.

---

## 🎯 Problem

AI-generated SQL has real challenges:

- ❌ Ambiguous natural language
- ❌ Schema mismatches
- ❌ Hallucinated tables/columns
- ❌ Version incompatibility (PostgreSQL 16 vs 17 vs 18)
- ❌ No validation layer

---

## 🚀 Solution

This project builds a **version-aware NL-to-SQL system** that:

1. Understands database schema
2. Generates SQL using AI
3. Validates correctness
4. Ensures compatibility with PostgreSQL versions

---

## 🧠 System Architecture

> Replace this image after generation

```md
![Architecture](images/architecture.png)