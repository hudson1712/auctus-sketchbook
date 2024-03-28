import streamlit as st
import datetime as dt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import os
import textwrap

def wrap_text(text, max_width, _font):
    # Split the text into lines based on the maximum width
    lines = []
    words = text.split(' ')
    
    current_line = ''
    for word in words:
        test_line = current_line + word + ' '
        line_width = _font.getlength(test_line)
        if line_width <= max_width:
            current_line = test_line
        else:
            lines.append(current_line[:-1])
            current_line = word + ' '
 
    lines.append(current_line[:-1])
    return lines

def draw_text_with_outline(_draw, position, text, _font, text_color, outline_color, outline_width):
    # Draw outline by offsetting the text position in all directions
    x, y = position
    for dx in range(-outline_width, outline_width+1):
        for dy in range(-outline_width, outline_width+1):
            if dx == 0 and dy == 0:
                continue  # Skip the offset for the main text
            _draw.text((x + dx, y + dy), text, font=_font, fill=outline_color)
    # Draw the main text
    _draw.text((x, y), text, font=_font, fill=text_color)

def add_text_to_image(image, y_offset, sentence, _font, font_size, line_spacing, text_color, outline_color, outline_width=8):
    
    # Apply line wrap if the text is longer than the image width
    max_width = int(image.width)
    wrapped_text = wrap_text(sentence, max_width, _font)
    
    # Calculate the vertical position of the text
    draw = ImageDraw.Draw(image)
    y = (image.height - int(font_size * len(wrapped_text) * line_spacing)) // 2 + y_offset
    
    # Draw the text
    for line in wrapped_text:
        line_width = _font.getlength(line)  # Use getlength for Pillow >= 8.0.0
        x = (image.width - line_width) // 2
        draw_text_with_outline(draw, (x, y), line, _font, text_color, outline_color, outline_width)
        y += int(font_size * line_spacing)

@st.cache_data
def add_gradient(image, gradient_type, gradient_offset=0):
    # Load the image and get its size
    width, height = image.size
    pixels = image.load()  # Load pixel data
    
    if gradient_type == "Top":
        for y in range(height - gradient_offset):
            for x in range(width):
                blend_factor = 1 - ((y) / (height - gradient_offset))
                pixels[x, y] = tuple([int(c * (1-blend_factor)) for c in pixels[x, y][:3]])  # Blend towards black
    
    elif gradient_type == "Bottom":
        for y in range(gradient_offset, height):
            for x in range(width):
                blend_factor = (y - gradient_offset) / (height - gradient_offset)
                pixels[x, y] = tuple([int(c * (1-blend_factor)) for c in pixels[x, y][:3]])  # Blend towards black

    return image

def main():
    #################################-- INITIALISE APP --#################################
    st.set_page_config(layout="wide")
    # Load fonts from local directory
    fonts_dir = 'app/fonts'
    fonts = [f for f in os.listdir(fonts_dir) if f.endswith('.ttf') or f.endswith('.otf')]

    logo = True
    if logo:
        st.sidebar.markdown("[<img src=\"https://cdn.auctusdigital.co.uk/settings/image/logoadmin-170775092190422.png\">](https://blueprint.auctusdigital.co.uk/)", unsafe_allow_html=True)
        st.markdown("<style>.st-emotion-cache-eqffof.e1nzilvr5 img {width: 100px; height: 100px;}</style>", unsafe_allow_html=True)

    # Title of the app and layout setup
    st.title('Image Text Editor')
    col1, col2 = st.columns((2,1))

    #################################-- TEXT EDITING --#################################
    # File uploader allows user to add their own image
    uploaded_image = col1.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

    if uploaded_image is not None:
        with col1:
            #Display the uploaded image and text box
            image = Image.open(uploaded_image)
            s1, s2 = st.columns((11, 3))
            text = s1.text_input("Text to add:", "THIS IS SOME REALLY LONG TEXT")
            selected_font = s2.selectbox("Choose a font", fonts, index=2)

            #Get uploaded image dimensions
            width, height = image.size
            
            #Options for the text
            o1, o2, o3, o4, o5, o6 = st.columns((1, 1, 3, 3, 3, 3))
            text_color = o1.color_picker("Text Color", "#FFFFFF")
            outline_color = o2.color_picker("Outline Color", "#000000")
            font_size = o3.number_input("Font Size", 0, 256, int(width*0.1), step=10)
            outline_width = o4.number_input("Outline Width", 1, 16, 8)
            line_spacing = o5.number_input("Line Spacing", 0.0, 5.0, 1.0, step=0.1)
            y_pos = o6.number_input("Y Position", -height, height, int(height*0.3), step=10)

            gradient_offset = o5.number_input("Gradient Offset", 0, height, int(height/2), step=50)
            gradient = o6.selectbox("Gradient", ["Top", "Bottom", "None"], index=1)

            font_path = os.path.join(fonts_dir, selected_font)
            font = ImageFont.truetype(font_path, font_size)

            editable_image = image.copy()

            #Add gradient
            editable_image = add_gradient(editable_image, gradient, gradient_offset)

            #Draw centred and wrapped text
            add_text_to_image(editable_image, y_pos, text, font, font_size, line_spacing, text_color, outline_color, outline_width)
    
    #################################-- IMAGE DISPLAY --#################################

        #Display the edited image on the right of the screen
        with col2:
            col2.image(editable_image, use_column_width=True)

            # Save and download functionality
            buf = BytesIO()
            editable_image.save(buf, format="PNG")
            byte_im = buf.getvalue()
            timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + '-'+str(np.random.randint(1000, 9999))
            col2.download_button(
                label="Download image",
                data=byte_im,
                file_name="image-{}.png".format(timestamp),
                mime="image/png"
            )

if __name__ == '__main__':
    main()