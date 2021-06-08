import os
import torch
import random
from typing import Optional, List, Tuple, Double
from .imagelist import ImageList, num_classes
from ._util import download as download_data, check_exits


class CheckerboardOfficeHome(ImageList):
    """`OfficeHome <http://hemanthdv.org/OfficeHome-Dataset/>`_ Dataset.

    Args:
        root (str): Root directory of dataset
        task (str): The task (domain) to create dataset. Choices include ``'Ar'``: Art, \
            ``'Cl'``: Clipart, ``'Pr'``: Product and ``'Rw'``: Real_World.
        download (bool, optional): If true, downloads the dataset from the internet and puts it \
            in root directory. If dataset is already downloaded, it is not downloaded again.
        transform (callable, optional): A function/transform that  takes in an PIL image and returns a \
            transformed version. E.g, :class:`torchvision.transforms.RandomCrop`.
        target_transform (callable, optional): A function/transform that takes in the target and transforms it.

    .. note:: The objects are labeled i = C*S_i + C_i where C is the number of categories, C_i is the category label of the object, and S_i is the style index of the object. This is so you can retrieve the category of the the object (S_i = i % C) and the style of the object (C_i = i // C).

    .. note:: In `root`, there will exist following files after downloading.
        ::
            Art/
                Alarm_Clock/*.jpg
                ...
            Clipart/
            Product/
            Real_World/
            image_list/
                train.txt
                val.txt
                test.txt
                novel.txt
    """
    download_list = [
        ("Art", "Art.tgz",
         "https://cloud.tsinghua.edu.cn/f/4691878067d04755beab/?dl=1"),
        ("Clipart", "Clipart.tgz",
         "https://cloud.tsinghua.edu.cn/f/0d41e7da4558408ea5aa/?dl=1"),
        ("Product", "Product.tgz",
         "https://cloud.tsinghua.edu.cn/f/76186deacd7c4fa0a679/?dl=1"),
        ("Real_World", "Real_World.tgz",
         "https://cloud.tsinghua.edu.cn/f/dee961894cc64b1da1d7/?dl=1")
    ]
    images_dirs = {
        "Ar": "Art/",
        "Cl": "Clipart/",
        "Pr": "Product/",
        "Rw": "Real_World/",
    }

    image_lists = {
        "train": "train.txt",
        "val": "val.txt",
        "test": "test.txt",
        "novel": "novel.txt"
    }

    CATEGORIES = [
        'Drill', 'Exit_Sign', 'Bottle', 'Glasses', 'Computer', 'File_Cabinet',
        'Shelf', 'Toys', 'Sink', 'Laptop', 'Kettle', 'Folder', 'Keyboard',
        'Flipflops', 'Pencil', 'Bed', 'Hammer', 'ToothBrush', 'Couch', 'Bike',
        'Postit_Notes', 'Mug', 'Webcam', 'Desk_Lamp', 'Telephone', 'Helmet',
        'Mouse', 'Pen', 'Monitor', 'Mop', 'Sneakers', 'Notebook', 'Backpack',
        'Alarm_Clock', 'Push_Pin', 'Paper_Clip', 'Batteries', 'Radio', 'Fan',
        'Ruler', 'Pan', 'Screwdriver', 'Trash_Can', 'Printer', 'Speaker',
        'Eraser', 'Bucket', 'Chair', 'Calendar', 'Calculator', 'Flowers',
        'Lamp_Shade', 'Spoon', 'Candles', 'Clipboards', 'Scissors', 'TV',
        'Curtains', 'Fork', 'Soda', 'Table', 'Knives', 'Oven', 'Refrigerator',
        'Marker'
    ]

    has_gen_file_list = False
    num_categories = len(CATEGORIES)
    num_styles = len(images_dirs.keys())
    cat_style_matrix = torch.zeros(
        (num_styles, num_categories)
    )

    def __init__(self,
                 root: str,
                 tasks: List[str],
                 dataset_type: str,
                 download: Optional[bool] = False,
                 **kwargs):
        assert dataset_type in CheckerboardOfficeHome.image_lists.keys()
        if download:
            list(
                map(lambda args: download_data(root, *args),
                    self.download_list))
        else:
            list(
                map(lambda file_name, _: check_exits(root, file_name),
                    self.download_list))
        if not CheckerboardOfficeHome.has_gen_file_list:
            CheckerboardOfficeHome.generate_image_list(root=root)
        super(CheckerboardOfficeHome, self).__init__(
            # TODO: Adapt the code for predicting style instead of category
            root=root,
            classes=CheckerboardOfficeHome.CATEGORIES,
            data_list_files=CheckerboardOfficeHome.image_lists[dataset_type],
            **kwargs)

    @classmethod
    def generate_image_list(
            cls,
            root: str,
            train_val_test_split: Optional[Tuple[Double]] = (0.5, 0.25, 0.25),
            domains_per_cat: Optional[int] = 2,
            style_is_domain: Optional[bool] = True):
        # TODO: Produce image list if style-predicting instead of category-predicting
        assert len(train_val_test_split) == 3 and sum(
            train_val_test_split) == 1
        cls.train_split, cls.val_split, cls.test_split = train_val_test_split
        train = []
        novel_list = ""
        
        styles = cls.image_dirs.keys()
        style_indices = list(range(cls.num_styles))
        

        for cat_index in range(cls.num_categories):
            random.shuffle(style_indices)
            style_count = 0
            for style_index in style_indices:
                image_dir = os.path.join(
                    root,
                    cls.image_dirs[styles[style_index]],
                    cls.CATEGORIES[cat_index])
                for filename in os.listdir(image_dir):
                    if filename.endswith(".jpg"):
                        label = cls._get_label(style_index, cat_index)
                        path_and_label = filename + ' ' + label + '\n'
                        if style_count < domains_per_cat:
                            train.append(path_and_label)
                            cls.cat_style_matrix[style_index, cat_index] = 1
                        else:
                            novel_list += path_and_label
                style_count += 1

        # training, validation/calibration, testing split
        random.shuffle(train)
        num_train = int(len(train) * cls.train_split)
        num_val = int(len(train) * cls.val_split)
        train_list = "".join(train[:num_train])
        val_list = "".join(train[num_train:(num_train + num_val)])
        test_list = "".join(train[(num_train + num_val):])

        train_list_filename = os.path.join(
            root, cls.image_lists['train'])
        val_list_filename = os.path.join(
            root, cls.images_dirs["val"])
        test_list_filename = os.path.join(
            root, cls.images_dirs["dir"])
        novel_list_filename = os.path.join(
            root, cls.image_lists['novel'])
        with open(train_list_filename, "w") as f:
            f.write(train_list)
        with open(val_list_filename, "w") as f:
            f.write(val_list)
        with open(test_list_filename, "w") as f:
            f.write(test_list)
        with open(novel_list_filename, "w") as f:
            f.write(novel_list)
        cls.has_gen_file_list = True

    def __str__(self):
        str_matrix = "Categories (Cols) AND Styles (Rows) Matrix\n "
        style_index = 0
        for cat_index in range(self.num_categories):
            str_matrix += "|" + cat_index
        str_matrix += "|\n"
        for row in CheckerboardOfficeHome.cat_style_matrix:
            str_matrix += "|" + style_index
            for val in row:
                if val == 1:
                    str_matrix += "|X"
                else:
                    str_matrix += "| "
            str_matrix += "|\n"
            style_index += 1
        return str_matrix

    @classmethod
    def domains(cls):
        if cls.style_is_domain:
            return list(cls.images_dirs.keys())
        else:
            return CheckerboardOfficeHome.CATEGORIES

    @classmethod
    def _get_label(cls, style_index: int, category_index: int) -> int:
        return cls.num_categories * style_index + category_index

    @classmethod
    def get_category(cls, labels: torch.tensor) -> torch.tensor:
        return labels % cls.num_categories

    @classmethod
    def get_style(cls, labels: torch.tensor) -> torch.tensor:
        return labels // cls.num_categories