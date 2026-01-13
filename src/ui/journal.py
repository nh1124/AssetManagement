import streamlit as st
import json

def render_journal():
    st.markdown('<h2 class="main-header">Journal: AI Entry</h2>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Receipt Upload & Smart Analysis</p>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Upload Receipt")
        uploaded_file = st.file_uploader("Choose a receipt image...", type=["jpg", "png", "jpeg"])
        if uploaded_file is not None:
            st.image(uploaded_file, caption="Uploaded Image", use_container_width=True)
            st.success("File uploaded successfully!")
        else:
            st.info("Please upload a receipt image to begin AI analysis.")

    with col2:
        st.subheader("AI Analysis Result (Mockup)")
        if uploaded_file:
            # Mock AI analysis
            result = {
                "items": [
                    {"name": "Eggs (10pcs)", "price": 280, "quantity": 1},
                    {"name": "Milk (1L)", "price": 240, "quantity": 2},
                    {"name": "Bread", "price": 180, "quantity": 1}
                ],
                "total": 880,
                "merchant": "MyLocal Supermarket",
                "category": "Food"
            }
            
            st.json(result)
            
            st.warning("⚠️ **Price of Eggs** is 20% higher than your standard cost param.")
            st.info("💡 Tip: Consider buying at ShopB for cheaper prices.")
            
            if st.button("Confirm & Save Transaction"):
                st.balloons()
                st.success("Transaction recorded!")
        else:
            st.write("Results will appear here after upload.")
