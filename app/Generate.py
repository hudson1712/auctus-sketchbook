import requests
from PIL import Image
import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
from fire_state import create_store, form_update, get_state, set_state, get_store, set_store
from io import BytesIO
import datetime as dt
import numpy as np
import openai
from openai import OpenAI
import boto3
from botocore.client import Config
from dataplane import s3_upload
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
import streamlit as st
import webbrowser

redirect_uri = st.secrets["REDIRECT_URI_GEN_CREATIVES"]

def auth_flow():
    st.write("Please Login to continue")
    auth_code = st.query_params.get("code")
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "app/logins/oauth_creds.json", # replace with you json credentials from your google auth app
        scopes=["https://www.googleapis.com/auth/userinfo.email", "openid"],
        redirect_uri=redirect_uri,
    )
    if auth_code:
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials
        user_info_service = build(
            serviceName="oauth2",
            version="v2",
            credentials=credentials,
        )
        user_info = user_info_service.userinfo().get().execute()
        assert user_info.get("email"), "Email not found in infos"
        st.session_state["google_auth_code"] = auth_code
        st.session_state["user_info"] = user_info
    else:
        if st.button("Sign in with Google"):
            authorization_url, state = flow.authorization_url(
                access_type="offline",
                include_granted_scopes="true",
            )
            webbrowser.open(authorization_url)

def authorise():
    if "google_auth_code" not in st.session_state:
        auth_flow()

    if "google_auth_code" in st.session_state:
        email = st.session_state["user_info"].get("email")
        st.write(f"Logged in as {email}")
        st.session_state["authorised"] = True

def handle_openai_error(error):
    if error.__class__.__name__ == "APIConnectionError":
        message = "Issue connecting to OpenAI. Check your network settings, proxy configuration, SSL certificates, or firewall rules."
    elif error.__class__.__name__ == "APITimeoutError":
        message = "Request timed out. Retry your request after a brief wait."
    elif error.__class__.__name__ == "AuthenticationError":
        message = "API key or token was invalid, expired, or revoked. Contact sam.hudson@auctusdigital.co.uk or james.lilley@auctusdigital.co.uk for help."
    elif error.__class__.__name__ == "BadRequestError":
        message = "Your request was malformed or missing some required parameters, such as a token or an input. The error message should advise you on the specific error made. Check the documentation for the specific API method you are calling and make sure you are sending valid and complete parameters. You may also need to check the encoding, format, or size of your request data."
    elif error.__class__.__name__ == "ConflictError":
        message = "The resource was updated by another request. Try to update the resource again and ensure no other requests are trying to update it."
    elif error.__class__.__name__ == "InternalServerError":
        message = "Issue on OpenAI server side. Retry your request after a brief wait."
    elif error.__class__.__name__ == "NotFoundError":
        message = "Requested resource does not exist. Ensure you are the correct resource identifier."
    elif error.__class__.__name__ == "PermissionDeniedError":
        message = "You don't have access to the requested resource. Ensure you are using the correct API key, organization ID, and resource ID."
    elif error.__class__.__name__ == "RateLimitError":
        message = "You have hit your assigned rate limit. Pace your requests. Track usage at https://platform.openai.com/usage."
    elif error.__class__.__name__ == "UnprocessableEntityError":
        message = "Unable to process the request despite the format being correct. Please try the request again."
    else:
        message = "An unknown error occurred."

    print(message)
    st.error(message)  # Display the error in Streamlit

@st.cache_data
def calc_costs(model, number, shape):
    if model == "dall-e-2":
        if shape == "256x256":
            return number * 0.016
        elif shape == "512x512":
            return number * 0.018
        elif shape == "1024x1024":
            return number * 0.02
    elif model == "dall-e-3":
        return number * 0.04

def get_byte_array_from_url(url):
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))
    img = img.convert("RGB")
    image_bytes = BytesIO()
    img.save(image_bytes, format="PNG")
    image_bytes = image_bytes.getvalue()
    return image_bytes

def upload_image_to_cloudflare(image_bytes_array):

    filepath = dt.datetime.now().strftime("%Y/%m/%d/") + str(np.random.randint(10000, 99999))

    # Connect to S3 client
    S3Connect = boto3.client(
        's3',
        endpoint_url=st.secrets['CLOUDFLARE_CONNECTION_URL'],
        aws_access_key_id=st.secrets['CLOUDFLARE_API_KEY'],
        aws_secret_access_key=st.secrets['CLOUDFLARE_API_SECRET'],
        config=Config(signature_version='s3v4'),
    )
    try:
        # Upload the file
        response = s3_upload(Bucket=st.secrets['CLOUDFLARE_BUCKET'], 
            S3Client=S3Connect,
            TargetFilePath=f"generated_images/{filepath}.png",
            UploadObject=image_bytes_array,
            UploadMethod=""
        )
        return response
    except FileNotFoundError:
        print("The file was not found")
        return None

#@st.cache_data
def refine_prompt(_client, prompt):
    base_prompt = "Refine the following text prompt for an image generation model, describe a captivating but simple image related to the prompt and add more detail and some creative aspects, ideally stylising the image in an interesting way. Be precise with the positioning of the subjects and avoid including too many unrelated details and any text. Return only the detailed text of the prompt to be sent to the image generation model, being as concise as possible and using keywords. The prompt to refine is: "
    instruction = base_prompt + prompt
    try:
        response = _client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "user", "content": instruction}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print("Failed to refine prompt: " + e)
        st.write("Failed to refine prompt with error (contact sam.hudson@auctusdigital.co.uk): " + e)        
        handle_openai_error(e)
        return prompt

#@st.cache_data
def generate_images_from_prompt(_client, prompt, number=1, model="dall-e-2", shape="256x256"):
    image_urls = []
    if model == "dall-e-3":
        shape = "1024x1024"
    for n in range(number):
        try:
            response = _client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size=shape
            )
            image_urls.append(response.data[0].url)
            try:
                upload_image_to_cloudflare(get_byte_array_from_url(response.data[0].url))
            except:
                print("Failed to upload image to Cloudflare")
                st.write("Failed upload image to Cloudflare, please download the image manually")

        except Exception as e:
            handle_openai_error(e)
            print("Failed to generate image")
            print(e)
            st.write("Failed to refine prompt with error (contact sam.hudson@auctusdigital.co.uk): " + e)

    return image_urls

#@st.cache_data
def generate_variations(_client, _image=None, number=1, model="dall-e-2", shape="256x256"):
    image_urls = []
    if model == "dall-e-3":
        shape = "1024x1024"
        number = 1
    try:
        response = _client.images.create_variation(
            image=_image,
            n=number,
            size=shape
        )
        for image in response.data:
            image_urls.append(image.url)
            try:
                upload_image_to_cloudflare(get_byte_array_from_url(image.url))
            except:
                print("Failed to upload image to Cloudflare")
                st.write("Failed upload image to Cloudflare, please download the image manually")

    except Exception as e:
        handle_openai_error(e)
        print("Failed to generate variations")
        print(e)
        st.write("Failed to refine prompt with error (contact sam.hudson@auctusdigital.co.uk): " + e)

        return None
    return image_urls

@st.cache_data(experimental_allow_widgets=True)
def display_images(image_urls):
    image_cols = st.columns(6)
    for column_i, image_url in enumerate(image_urls):
        try:
            image = Image.open(requests.get(image_url, stream=True).raw)
        except Exception:
            print(f"Failed to load image: URL has expired or is not an image: {image_url}")
            continue

        col = image_cols[column_i % 6]
        col.image(image, use_column_width=True)

        name = image_url[-10:]
        buf = BytesIO()
        image.save(buf, format="PNG")
        byte_im = buf.getvalue()

        col.download_button(
            label="Download Image",
            key="{}".format(name),
            data=byte_im,
            file_name="{}.png".format(name),
            mime="image/png"
        )

def streamlit_app():
    st.set_page_config(layout="wide")
    st.title("Image Generation and Refinement")

    #################################-- AUTHENTICATION --#################################
    st.session_state['authorised'] = False
    authorise()
    if st.session_state['authorised'] == True:
        #################################-- INITIALISE APP --#################################
        client = OpenAI(
            api_key=st.secrets['OPENAI_API_KEY'],
            organization=st.secrets['OPENAI_ORG'],
        )
        
        logo = True
        if logo:
            st.sidebar.markdown("[<img src=\"https://cdn.auctusdigital.co.uk/settings/image/logoadmin-170775092190422.png\">](https://blueprint.auctusdigital.co.uk/)", unsafe_allow_html=True)
            st.markdown("<style>.st-emotion-cache-eqffof.e1nzilvr5 img {width: 100px; height: 100px;}</style>", unsafe_allow_html=True)
                
        st.sidebar.header("Instructions for use")
        st.sidebar.markdown("**1. Enter an initial prompt**: This can be a headline for an article or a description of an image.")
        st.sidebar.markdown("**2. Refine Prompt**: Use ChatGPT to refine the prompt, this will improve the descriptiveness and may give better results/ideas. The refined prompt can be edited and is the prompt that will be sent to the image generation model.")
        st.sidebar.markdown("**3. Select Model**: Dall-E 3 is the best model but the most expensive. It only works with 1024x1024 images. Dall-E 2 is cheaper and can generate images of any size but produces poorer images, use this if you have a lot of images to generate/want to get general ideas.")
        st.sidebar.markdown("**4. Generate Images**: Click the button to generate images based on the **refined** prompt. After running the images should appear below with download links. Image links will expire 1 hour after generating so download them if you need them. To tweak the images, just edit the refined prompt and click generate again.")
        st.sidebar.markdown("**5. Select Images to refine**: You can drag and drop generated images directly into the upload box to generate variations of them. Variations on an existing image can only be generated by Dall-E 2 so the quality will be poorer, use the largest size for best results.")
        st.sidebar.markdown("**Costs**: Dall-E 2 is \$0.02 per image and Dall-E 3 is \$0.04 per image (Standard quality 1024x1024). Dall-E 3 can be set to HD mode and costs \$0.08 per image. GPT prompt refining cost: peanuts")

        #Initialise session state
        if 'initialised' not in st.session_state:
            st.session_state["generated_image_urls"] = []
            st.session_state["prompt"] = None
            st.session_state["initial_prompt"] = None
            st.session_state["generate_images"] = False
            st.session_state['generate_variations'] = False
            st.session_state["initialised"] = True

        #################################-- IMAGE GENERATION --#################################
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Create new images from prompts")

            s1, s2, s3 = st.columns(3)
            number_of_images = s1.number_input("Number of images to generate", min_value=1, max_value=10, value=1)
            model_to_use = s2.selectbox("Select generation model", ["dall-e-2", "dall-e-3"], index=1)
            image_size = s3.selectbox("Image size", ["256x256", "512x512", "1024x1024"], index=2)
            est_cost = calc_costs(model_to_use, number_of_images, image_size)

            #Take the initial prompt from the user for generating an image
            st.session_state["initial_prompt"] = st.text_input("Enter an initial prompt / article headline: ")

            # Refine the prompt using GPT-3.5, repeated pressing will generate a new prompt
            if st.button("Refine Prompt using GPT-3.5"):
                st.session_state["prompt"] = refine_prompt(client, st.session_state["initial_prompt"])

            # Display the prompt to be sent to the image generation model and allow editing
            if st.session_state.get("prompt") is not None:  
                st.session_state["prompt"] = st.text_area("**Refined prompt**:", value=st.session_state["prompt"], height=200)

            # Submit the prompt and generate images
            sub_col_1, sub_col_2 = st.columns((2,1))
            if sub_col_1.button("Generate Images from prompt"):
                st.session_state["generate_images"] = True
            sub_col_2.write(f"Estimated cost: ${est_cost}")

            # Generate the images and store them in session state
            if st.session_state.get("generate_images") is True:

                # Handle the case where the user has not refined/entered a prompt
                if st.session_state.get("prompt") is None or st.session_state["prompt"] == "":
                    st.session_state["prompt"] = st.session_state["initial_prompt"]
                    st.session_state["generate_images"] = False

                st.session_state["generated_image_urls"].extend(generate_images_from_prompt(client, prompt=st.session_state["prompt"], model=model_to_use, number=number_of_images, shape=image_size))
                st.session_state["generate_images"] = False
            
        #################################-- VARIATION GENERATION --#################################
        with col2:
            st.subheader("Generate Variations on existing images")
            sc1, sc2 = st.columns((2,1))
            #If the user uploads an image, allow them to generate variations on the image
            uploaded_image = sc1.file_uploader("Upload an image as a starting point", type=["png", "jpg", "jpeg"])
            
            if uploaded_image is not None:
                image = Image.open(uploaded_image)
                with BytesIO() as buffer:
                    image.save(buffer, format="PNG")
                    buffer.seek(0)
                    image_png = Image.open(buffer)
                    byte_array = buffer.getvalue()  # PNG byte array for further processing

                    # Display the converted (or reaffirmed) PNG image
                    sc2.image(image_png, use_column_width=True)
                    st.write("Image successfully uploaded and ready for processing.")

            option_col_1, option_col_2 = st.columns(2)
            number_of_variations = option_col_1.number_input("Number of Variations", min_value=1, max_value=10, value=1)
            image_var_size = option_col_2.selectbox("Select variation image size", ["256x256", "512x512", "1024x1024"], index=2)

            if st.button("Generate Variations"):
                if uploaded_image is None:
                    st.markdown("<span style=\"color:red\">Please upload an image first</span>", unsafe_allow_html=True)
                    return
                st.session_state['generate_variations'] = True

            if st.session_state.get("generate_variations") is True:
                st.session_state["generated_image_urls"].extend(generate_variations(client, number=number_of_variations, _image=byte_array, shape=image_var_size))
                st.session_state["generate_variations"] = False

        #Display the images if generated
        if st.session_state.get("generated_image_urls") is not None:
            display_images(st.session_state["generated_image_urls"])
        
if __name__ == "__main__":
    streamlit_app()