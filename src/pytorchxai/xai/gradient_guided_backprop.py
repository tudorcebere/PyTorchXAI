import torch
from torch.nn import ReLU

from pytorchxai.xai.utils import (
    convert_to_grayscale,
    get_positive_negative_saliency,
    normalize_gradient
)


class GuidedBackprop:
    """
       Produces gradients generated with guided back propagation from the given image
    """

    def __init__(self, model):
        self.model = model
        self.gradients = None
        self.forward_relu_outputs = []
        # Put model in evaluation mode
        self.model.eval()
        self.update_relus()
        self.hook_layers()

    def hook_layers(self):
        def hook_function(module, grad_in, grad_out):
            self.gradients = grad_in[0]

        # Register hook to the first layer
        first_layer = list(self.model.features._modules.items())[0][1]
        first_layer.register_backward_hook(hook_function)

    def update_relus(self):
        """
            Updates relu activation functions so that
                1- stores output in forward pass
                2- imputes zero for gradient values that are less than zero
        """

        def relu_backward_hook_function(module, grad_in, grad_out):
            """
            If there is a negative gradient, change it to zero
            """
            # Get last forward output
            corresponding_forward_output = self.forward_relu_outputs[-1]
            corresponding_forward_output[corresponding_forward_output > 0] = 1
            modified_grad_out = corresponding_forward_output * torch.clamp(
                grad_in[0], min=0.0
            )
            del self.forward_relu_outputs[-1]  # Remove last forward output
            return (modified_grad_out,)

        def relu_forward_hook_function(module, ten_in, ten_out):
            """
            Store results of forward pass
            """
            self.forward_relu_outputs.append(ten_out)

        # Loop through layers, hook up ReLUs
        for pos, module in self.model.features._modules.items():
            if isinstance(module, ReLU):
                module.register_backward_hook(relu_backward_hook_function)
                module.register_forward_hook(relu_forward_hook_function)

    def generate_gradients(self, input_image, target_class):
        # Forward pass
        model_output = self.model(input_image)
        # Zero gradients
        self.model.zero_grad()
        # Target for backprop
        one_hot_output = torch.FloatTensor(1, model_output.size()[-1]).zero_()
        one_hot_output[0][target_class] = 1
        # Backward pass
        model_output.backward(gradient=one_hot_output)
        # Convert Pytorch variable to numpy array
        # [0] to get rid of the first channel
        gradients_as_arr = self.gradients.data.numpy()[0]
        return gradients_as_arr

    def generate(self, input_image, target_class):
        guided_grads = self.generate_gradients(input_image, target_class)

        color_guided_grads = normalize_gradient(guided_grads)
        grayscale_guided_grads = normalize_gradient(convert_to_grayscale(guided_grads))

        pos_sal, neg_sal = get_positive_negative_saliency(guided_grads)
        pos_sal_grads = normalize_gradient(pos_sal)
        neg_sal_grads = normalize_gradient(neg_sal)

        return {
            "color_guided_grads": color_guided_grads,
            "grayscale_guided_grads": grayscale_guided_grads,
            "positive_saliency_maps": pos_sal_grads,
            "negative_saliency_maps": neg_sal_grads,
        }