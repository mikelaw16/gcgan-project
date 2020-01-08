import torch
import torchvision
import torchvision.transforms as transforms
import torch.utils.data as data
import h5py


class get_usps_dataset_16x16(data.Dataset):
    def __init__(self, spec):
        self.mode = spec['mode'] # either 'train' or 'test'
        self.root = spec['root']
        self.images = None
        self.labels = None
        # self.transforms = spec['transforms'] # Already transformed (?)

        with h5py.File('usps.h5', 'r') as hf:
            data = hf.get(self.mode)
            self.images = data.get('data')[:]
            self.images = torch.as_tensor(self.images).reshape(-1, 1, 16, 16)
            self.labels = data.get('target')[:]
            self.labels = torch.as_tensor(self.labels)

    def __len__(self):
        return self.images.size()[0]

    def __getitem__(self, index):
        return self.images[index], self.labels[index]


class UnsqueezeSingleChannel(object):
    def __init__(self):
        pass

    def __call__(self, img):
        return torch.unsqueeze(img, dim=0)


class ComposedTransforms:

    usps_transf = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,)),
        UnsqueezeSingleChannel()  # Add extra dimension for the single channel
    ])

    mnist_transf = transforms.Compose([
        transforms.Resize(16),
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,)),
    ])


def get_train_loaders(config):
    usps_spec = {'mode': 'train',
                 'root': 'USPSdata'}
                 # 'transforms': ComposedTransforms.usps_transf}

    usps_dataset = get_usps_dataset_16x16(usps_spec)
    usps_loader = data.DataLoader(dataset=usps_dataset,
                                  batch_size=config.batch_size,
                                  shuffle=True,
                                  num_workers=config.num_workers)

    mnist_dataset = torchvision.datasets.MNIST(root='./MNIST',
                                               train=True,
                                               download=True,
                                               transform=ComposedTransforms.mnist_transf)

    mnist_loader = data.DataLoader(dataset=mnist_dataset,
                                   batch_size=config.batch_size,
                                   shuffle=True,
                                   num_workers=config.num_workers)
    return usps_loader, mnist_loader


def get_usps_test_loader(batch_size):
    usps_spec = {'mode': 'test',
                 'root': 'USPSdata'}
                 # 'transforms': ComposedTransforms.usps_transf}
    usps_test_dataset = get_usps_dataset_16x16(usps_spec)
    usps_test_loader = data.DataLoader(dataset=usps_test_dataset,
                                       batch_size=batch_size,
                                       shuffle=True)
    return usps_test_loader
