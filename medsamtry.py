# -*- coding: utf-8 -*-
"""Another copy of medsam.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1zKsmbylUl-km2hAR5uSCXP2CfolDT-DU
"""



from google.colab import drive
drive.mount('/content/drive')

!pip install -q git+https://github.com/bowang-lab/MedSAM.git

# %% environment and functions
import numpy as np
import matplotlib.pyplot as plt
import os
join = os.path.join
import torch
from segment_anything import sam_model_registry
from skimage import io, transform
import torch.nn.functional as F

# visualization functions
# source: https://github.com/facebookresearch/segment-anything/blob/main/notebooks/predictor_example.ipynb
# change color to avoid red and green
def show_mask(mask, ax, random_color=False):
    if random_color:
        color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
    else:
        color = np.array([251/255, 252/255, 30/255, 0.6])
    h, w = mask.shape[-2:]
    mask_image = mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
    ax.imshow(mask_image)

def show_box(box, ax):
    x0, y0 = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    ax.add_patch(plt.Rectangle((x0, y0), w, h, edgecolor='blue', facecolor=(0,0,0,0), lw=2))

@torch.no_grad()
def medsam_inference(medsam_model, img_embed, box_1024, H, W):
    box_torch = torch.as_tensor(box_1024, dtype=torch.float, device=img_embed.device)
    if len(box_torch.shape) == 2:
        box_torch = box_torch[:, None, :] # (B, 1, 4)

    sparse_embeddings, dense_embeddings = medsam_model.prompt_encoder(
        points=None,
        boxes=box_torch,
        masks=None,
    )
    low_res_logits, _ = medsam_model.mask_decoder(
        image_embeddings=img_embed, # (B, 256, 64, 64)
        image_pe=medsam_model.prompt_encoder.get_dense_pe(), # (1, 256, 64, 64)
        sparse_prompt_embeddings=sparse_embeddings, # (B, 2, 256)
        dense_prompt_embeddings=dense_embeddings, # (B, 256, 64, 64)
        multimask_output=False,
        )

    low_res_pred = torch.sigmoid(low_res_logits)  # (1, 1, 256, 256)

    low_res_pred = F.interpolate(
        low_res_pred,
        size=(H, W),
        mode="bilinear",
        align_corners=False,
    )  # (1, 1, gt.shape)
    low_res_pred = low_res_pred.squeeze().cpu().numpy()  # (256, 256)
    medsam_seg = (low_res_pred > 0.5).astype(np.uint8)
    return medsam_seg

# download model and data
!wget -O img_demo.png https://raw.githubusercontent.com/bowang-lab/MedSAM/main/assets/img_demo.png
!wget -O medsam_vit_b.pth https://zenodo.org/records/10689643/files/medsam_vit_b.pth

#%% load model and image
MedSAM_CKPT_PATH = "/content/medsam_vit_b.pth"
device = "cuda:0"
medsam_model = sam_model_registry['vit_b'](checkpoint=MedSAM_CKPT_PATH)
medsam_model = medsam_model.to(device)
medsam_model.eval()

img_np = io.imread('/content/drive/MyDrive/Stevenstuff/tiffiles/TCGA_CS_4941_19960909_11.tif')
if len(img_np.shape) == 2:
    img_3c = np.repeat(img_np[:, :, None], 3, axis=-1)
else:
    img_3c = img_np


if img_np.shape[-1] == 4:  # Check if the last dimension is 4 (RGBA)
    img_3c = img_np[:, :, :3]  # Extract the first 3 channels (RGB)
else:
    img_3c = img_np
H, W, _ = img_3c.shape

img_3c.shape

#%% image preprocessing and model inference
img_1024 = transform.resize(img_3c, (1024, 1024), order=3, preserve_range=True, anti_aliasing=True).astype(np.uint8)
img_1024 = (img_1024 - img_1024.min()) / np.clip(
    img_1024.max() - img_1024.min(), a_min=1e-8, a_max=None
)  # normalize to [0, 1], (H, W, 3)
# convert the shape to (3, H, W)
img_1024_tensor = torch.tensor(img_1024).float().permute(2, 0, 1).unsqueeze(0).to(device)

box_np = np.array([[80,50, 140, 120]])
# transfer box_np t0 1024x1024 scale
box_1024 = box_np / np.array([W, H, W, H]) * 1024
with torch.no_grad():
    image_embedding = medsam_model.image_encoder(img_1024_tensor) # (1, 256, 64, 64)

medsam_seg = medsam_inference(medsam_model, image_embedding, box_1024, H, W)

#%% visualize results
fig, ax = plt.subplots(1, 2, figsize=(10, 5))
ax[0].imshow(img_3c)
show_box(box_np[0], ax[0])
ax[0].set_title("Input Image and Bounding Box")
ax[1].imshow(img_3c)
show_mask(medsam_seg, ax[1])
show_box(box_np[0], ax[1])
ax[1].set_title("MedSAM Segmentation")
plt.show()

gt_mask = io.imread('/content/drive/MyDrive/Stevenstuff/tiffiles/TCGA_CS_4941_19960909_11_mask.tif')
fig_gt, ax_gt = plt.subplots(figsize=(5, 5))
ax_gt.imshow(gt_mask, cmap='gray')
ax_gt.set_title("Ground Truth Mask")

agt_mask = (gt_mask > 0).astype(np.uint8)

# Flatten the masks and compute the Dice loss
medsam_seg_flat = medsam_seg.flatten()
gt_mask_flat = gt_mask.flatten()

intersection = np.sum(medsam_seg_flat * gt_mask_flat)
union = np.sum(medsam_seg_flat) + np.sum(gt_mask_flat)
dice_loss = 1 - 2 * intersection / union

print(f"Dice loss: {dice_loss:.4f}")

# Define the directory containing the tif files
tif_dir = '/content/drive/MyDrive/Stevenstuff/tiffiles'

# Define the bounding boxes for each image
bounding_boxes = {
    'TCGA_CS_4941_19960909_11.tif': np.array([[80, 50, 140, 120]]),
    'TCGA_CS_4941_19960909_12.tif': np.array([[50, 40, 140, 120]]),
    'TCGA_CS_4941_19960909_13.tif': np.array([[50, 40, 140, 120]]),
    'TCGA_CS_4941_19960909_14.tif': np.array([[50, 40, 140, 120]]),
    'TCGA_CS_4941_19960909_15.tif': np.array([[50, 40, 140, 120]])
}

# List to store the dice losses
dice_losses = []

# Loop through all the tif files in the directory
for filename in os.listdir(tif_dir):
    if filename.endswith('.tif'):
        # Check if the corresponding mask file exists
        mask_filename = filename.replace('.tif', '_mask.tif')
        mask_path = os.path.join(tif_dir, mask_filename)
        if os.path.isfile(mask_path):
          if filename in bounding_boxes:
            # Load the image and mask
            img_path = os.path.join(tif_dir, filename)
            img_np = io.imread(img_path)
            gt_mask = io.imread(mask_path)

            # Preprocess the image
            if len(img_np.shape) == 2:
                img_3c = np.repeat(img_np[:, :, None], 3, axis=-1)
            else:
                img_3c = img_np

            if img_np.shape[-1] == 4:  # Check if the last dimension is 4 (RGBA)
                img_3c = img_np[:, :, :3]  # Extract the first 3 channels (RGB)
            else:
                img_3c = img_np
            H, W, _ = img_3c.shape

            # Get the bounding box for the current image
            box_np = bounding_boxes[filename]

            # Preprocess the image and perform MedSAM inference
            # ... (same as before)

            # Compute the dice loss
            agt_mask = (gt_mask > 0).astype(np.uint8)
            medsam_seg_flat = medsam_seg.flatten()
            gt_mask_flat = agt_mask.flatten()

            intersection = np.sum(medsam_seg_flat * gt_mask_flat)
            union = np.sum(medsam_seg_flat) + np.sum(gt_mask_flat)
            dice_loss = 1 - 2 * intersection / union

            # Append the dice loss to the list
            dice_losses.append(dice_loss)

            print(f"Dice loss for {filename}: {dice_loss:.4f}")
          else:
                print(f"Skipping {filename} (no bounding box coordinates)")

# Calculate the average dice loss
avg_dice_loss = sum(dice_losses) / len(dice_losses)
print(f"Average Dice loss: {avg_dice_loss:.4f}")

