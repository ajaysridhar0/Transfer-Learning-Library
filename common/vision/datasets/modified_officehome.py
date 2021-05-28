import os
from typing import Optional, List
from .imagelist import ImageList
from ._util import download as download_data, check_exits


class ModifiedOfficeHome(ImageList):
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
                Art.txt
                Clipart.txt
                Product.txt
                Real_World.txt
    """
    download_list = [
        ("image_list", "image_list.zip",
         "https://cloud.tsinghua.edu.cn/f/ca3a3b6a8d554905b4cd/?dl=1"),
        ("Art", "Art.tgz", "https://cloud.tsinghua.edu.cn/f/4691878067d04755beab/?dl=1"),
        ("Clipart", "Clipart.tgz",
         "https://cloud.tsinghua.edu.cn/f/0d41e7da4558408ea5aa/?dl=1"),
        ("Product", "Product.tgz",
         "https://cloud.tsinghua.edu.cn/f/76186deacd7c4fa0a679/?dl=1"),
        ("Real_World", "Real_World.tgz",
         "https://cloud.tsinghua.edu.cn/f/dee961894cc64b1da1d7/?dl=1")
    ]
    image_style_list = {
        "Ar": "image_list/Art.txt",
        "Cl": "image_list/Clipart.txt",
        "Pr": "image_list/Product.txt",
        "Rw": "image_list/Real_World.txt",
    }
    CATEGORIES = ['Drill', 'Exit_Sign', 'Bottle', 'Glasses', 'Computer', 'File_Cabinet', 'Shelf', 'Toys', 'Sink',
                  'Laptop', 'Kettle', 'Folder', 'Keyboard', 'Flipflops', 'Pencil', 'Bed', 'Hammer', 'ToothBrush', 'Couch',
                  'Bike', 'Postit_Notes', 'Mug', 'Webcam', 'Desk_Lamp', 'Telephone', 'Helmet', 'Mouse', 'Pen', 'Monitor',
                  'Mop', 'Sneakers', 'Notebook', 'Backpack', 'Alarm_Clock', 'Push_Pin', 'Paper_Clip', 'Batteries', 'Radio',
                  'Fan', 'Ruler', 'Pan', 'Screwdriver', 'Trash_Can', 'Printer', 'Speaker', 'Eraser', 'Bucket', 'Chair',
                  'Calendar', 'Calculator', 'Flowers', 'Lamp_Shade', 'Spoon', 'Candles', 'Clipboards', 'Scissors', 'TV',
                  'Curtains', 'Fork', 'Soda', 'Table', 'Knives', 'Oven', 'Refrigerator', 'Marker']

    def __init__(self, root: str, tasks: List[str], download: Optional[bool] = False, **kwargs):
        # TODO: Make it accept lists of styles
        # assert task in self.image_list
        for task in tasks:
            assert task in self.image_style_list
        data_list_file = os.path.join(root, self.image_style_list[task])
        self.num_categories = len(ModifiedOfficeHome.CATEGORIES)
        self.num_styles = len(ModifiedOfficeHome.image_style_list)
        self.was_modified_file_path = os.path.join(
            self.root, "has-modified.txt")
        if not self.was_modified_file_path.isfile():
            with open(self.was_modified_file_path, 'w') as f:
                f.write(str(False))
        if download:
            list(map(lambda args: download_data(root, *args), self.download_list))
            # check if the file has been modified
            with open(self.was_modified_file_path, 'r') as f:
                line = f.readline()
                was_modified = eval(line)
            if not was_modified:
                # modify the file with the new category-style label
                with open(self.was_modified_file_path, 'w') as f:
                    f.write(str(True))
                category_index = 0
                for file_name in self.image_style_list:
                    new_contents = ""
                    with open(file_name, "r") as f:
                        for line in f.readlines():
                            split_line = line.split()
                            target = split_line[-1]
                            path = ' '.join(split_line[:-1])
                            target = int(target)
                            new_target = str(
                                target + category_index * self.num_categories
                            )
                            new_contents += path + ' ' + new_target + '\n'
                    with open(file_name, "w") as f:
                        f.write(new_contents)
                    category_index += 1
        else:
            list(map(lambda file_name, _: check_exits(
                root, file_name), self.download_list))

        super(ModifiedOfficeHome, self).__init__(
            root, ModifiedOfficeHome.CATEGORIES, data_list_file=data_list_file, **kwargs)

    @classmethod
    def domains(cls):
        return list(cls.image_style_list.keys())
