import streamlit as st

st.title("Python Environment")
st.write("Welcome! Your Python environment is ready. Start coding below.")

st.markdown("---")

st.header("Try it out")

name = st.text_input("Enter your name", "World")
if name:
    st.success(f"Hello, {name}!")

st.markdown("---")

st.header("Quick calculator")
a = st.number_input("First number", value=0.0)
b = st.number_input("Second number", value=0.0)
operation = st.selectbox("Operation", ["Add", "Subtract", "Multiply", "Divide"])

if st.button("Calculate"):
    if operation == "Add":
        result = a + b
    elif operation == "Subtract":
        result = a - b
    elif operation == "Multiply":
        result = a * b
    elif operation == "Divide":
        if b != 0:
            result = a / b
        else:
            st.error("Cannot divide by zero!")
            result = None

    if result is not None:
        st.info(f"Result: {result}")

st.markdown("---")
st.caption("Edit app.py to start building your own Python app.")
